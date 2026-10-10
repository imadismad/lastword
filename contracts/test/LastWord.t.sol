// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {LastWord} from "../src/LastWord.sol";
import {DemoUSD} from "../src/DemoUSD.sol";
import {P256} from "@openzeppelin/contracts/utils/cryptography/P256.sol";

contract LastWordTest is Test {
    LastWord lw;
    DemoUSD usd;

    // actors
    address admin = address(0xA11CE);
    address coAdmin = address(0xC0ADA);
    address agent = address(0xA6E17);
    address bridge = address(0xB41D6E);
    address guardian = address(0x6DA12);
    address beneficiary = address(0x1111111111111111111111111111111111111111);
    address vault = address(0x7A017);
    address parallelVault = address(0xDEC00);

    // P-256 test private keys (test only)
    uint256 constant DAF_PK = 0xC001;
    uint256 constant STOCK_PK = 0x57C0;
    uint256 constant DURESS_PK = 0xD12E55;

    uint64 constant CAP = 1_000_000_000; // 1000 dUSD at 6 decimals
    uint64 constant DELAY = 1 days;
    uint64 constant PARALLEL_CAP = 50_000_000; // 50 dUSD decoy cap

    uint256 constant P256_N =
        0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551;

    function setUp() public {
        vm.warp(10_000_000); // move clock forward so backdating works
        usd = new DemoUSD();

        vm.prank(admin);
        lw = new LastWord(usd, vault, parallelVault, PARALLEL_CAP, DELAY);

        vm.prank(admin);
        lw.setRoles(agent, address(0), coAdmin, guardian, bridge);

        // register P-256 pubkeys (vm.publicKeyP256 returns uint256 x,y)
        (uint256 dqx, uint256 dqy) = vm.publicKeyP256(DAF_PK);
        (uint256 sqx, uint256 sqy) = vm.publicKeyP256(STOCK_PK);
        (uint256 uqx, uint256 uqy) = vm.publicKeyP256(DURESS_PK);
        vm.startPrank(admin);
        lw.registerDafKey(bytes32(dqx), bytes32(dqy));
        lw.registerStockKey(bytes32(sqx), bytes32(sqy));
        lw.registerDuressKey(bytes32(uqx), bytes32(uqy));
        lw.seedSupplierForDemo(beneficiary, CAP, DELAY + 1); // old enough, active
        vm.stopPrank();

        // fund both vaults and approve the contract to pull
        usd.mint(vault, 1_000_000_000_000);
        usd.mint(parallelVault, 1_000_000_000_000);
        vm.prank(vault);
        usd.approve(address(lw), type(uint256).max);
        vm.prank(parallelVault);
        usd.approve(address(lw), type(uint256).max);
    }

    // ------------------------------------------------------- intent builders
    function _intent(
        uint32 reqId, uint64 amount, uint32 nonce, uint32 deadline,
        bytes32 quoteHash, uint16 flags
    ) internal view returns (bytes memory) {
        return abi.encodePacked(
            uint8(1),                 // version
            uint8(1),                 // algorithm
            reqId,                    // u32
            bytes20(beneficiary),     // 20
            uint8(0),                 // token index 0
            amount,                   // u64
            nonce,                    // u32
            deadline,                 // u32
            quoteHash,                // 32
            flags,                    // u16
            uint16(1)                 // policy
        );
    }

    function _digest(bytes memory intent) internal view returns (bytes32) {
        return sha256(
            abi.encodePacked(
                bytes11("LASTWORD-v1"),
                uint64(block.chainid),
                address(lw),
                intent
            )
        );
    }

    function _signLowS(uint256 pk, bytes32 digest) internal pure returns (bytes32 r, bytes32 s) {
        (r, s) = vm.signP256(pk, digest);
        // normalize to low-s (what the bridge does)
        if (uint256(s) > P256_N / 2) {
            s = bytes32(P256_N - uint256(s));
        }
    }

    // full happy path up to attested; returns reqId and the DAF digest
    function _proposeAndAttest(uint32 reqId) internal returns (bytes32 dafDigest) {
        bytes32 quote = keccak256(abi.encodePacked("quote", reqId));
        uint32 deadline = uint32(block.timestamp + 600);

        // STOCK intent (role bits 01)
        bytes memory stockIntent = _intent(reqId, 250_000_000, 1, deadline, quote, 0x0001);
        vm.prank(agent);
        lw.propose(stockIntent, "");

        bytes32 stockDigest = _digest(stockIntent);
        (bytes32 sr, bytes32 ss) = _signLowS(STOCK_PK, stockDigest);
        vm.prank(bridge);
        lw.attestDelivery(reqId, sr, ss);

        // Both attest (stock key) and approve (DAF key) verify against the SAME
        // stored request digest. Role separation is enforced by which key signs.
        dafDigest = stockDigest;
    }

    // =====================================================================
    //  T-01 : P-256 verification (good and bad, including high-s)
    // =====================================================================
    function test_T01_p256_low_s_accepted_high_s_rejected() public view {
        bytes32 h = sha256("lastword-test");
        (uint256 qx, uint256 qy) = vm.publicKeyP256(DAF_PK);
        (bytes32 r, bytes32 s) = vm.signP256(DAF_PK, h);
        // force low-s
        bytes32 sLow = uint256(s) > P256_N / 2 ? bytes32(P256_N - uint256(s)) : s;
        bytes32 sHigh = bytes32(P256_N - uint256(sLow));

        assertTrue(P256.verify(h, r, sLow, bytes32(qx), bytes32(qy)), "low-s must verify");
        assertFalse(P256.verify(h, r, sHigh, bytes32(qx), bytes32(qy)), "high-s must be rejected");
    }

    // =====================================================================
    //  Nominal payment
    // =====================================================================
    function test_nominal_payment() public {
        uint32 reqId = 1;
        bytes32 digest = _proposeAndAttest(reqId);

        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, digest);
        uint256 beforeBal = usd.balanceOf(beneficiary);
        vm.prank(bridge);
        lw.approve(reqId, r, s);

        assertEq(uint256(usd.balanceOf(beneficiary) - beforeBal), 250_000_000);
    }

    // =====================================================================
    //  Forged / wrong-key signature refused
    // =====================================================================
    function test_forged_signature_refused() public {
        uint32 reqId = 2;
        bytes32 digest = _proposeAndAttest(reqId);
        // sign with the WRONG key (stock) presented as DAF approval
        (bytes32 r, bytes32 s) = _signLowS(STOCK_PK, digest);
        vm.prank(bridge);
        vm.expectRevert(LastWord.BadSignature.selector);
        lw.approve(reqId, r, s);
    }

    // =====================================================================
    //  Tampered parameter after approval -> different digest -> invalid sig
    // =====================================================================
    function test_tampered_digest_refused() public {
        uint32 reqId = 3;
        _proposeAndAttest(reqId);
        // sign a DIFFERENT digest than the stored request's
        bytes32 wrongDigest = sha256("not the right digest");
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, wrongDigest);
        vm.prank(bridge);
        vm.expectRevert(LastWord.BadSignature.selector);
        lw.approve(reqId, r, s);
    }

    // =====================================================================
    //  Replay: nonce used once
    // =====================================================================
    function test_replay_nonce_refused() public {
        // First request: reqId 4, nonce 1 (from _proposeAndAttest) -> approved OK.
        uint32 reqId = 4;
        bytes32 digest = _proposeAndAttest(reqId);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, digest);
        vm.prank(bridge);
        lw.approve(reqId, r, s);

        // Second request reusing the SAME approver nonce (1) must be refused at approve.
        uint32 reqId2 = 6;
        bytes32 quote = keccak256(abi.encodePacked("quote-replay", reqId2));
        uint32 deadline = uint32(block.timestamp + 600);
        bytes memory stockIntent = _intent(reqId2, 100_000_000, 1, deadline, quote, 0x0001);
        vm.prank(agent);
        lw.propose(stockIntent, "");
        bytes32 sd = _digest(stockIntent);
        (bytes32 sr, bytes32 ss) = _signLowS(STOCK_PK, sd);
        vm.prank(bridge);
        lw.attestDelivery(reqId2, sr, ss);
        (bytes32 r2, bytes32 s2) = _signLowS(DAF_PK, sd);
        vm.prank(bridge);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 99));
        lw.approve(reqId2, r2, s2);
    }

    // =====================================================================
    //  Expired deadline refused
    // =====================================================================
    function test_expired_refused() public {
        uint32 reqId = 10;
        bytes32 quote = keccak256("q10");
        uint32 deadline = uint32(block.timestamp + 600);
        bytes memory stockIntent = _intent(reqId, 100_000_000, 3, deadline, quote, 0x0001);
        vm.prank(agent);
        lw.propose(stockIntent, "");
        bytes32 sd = _digest(stockIntent);
        (bytes32 sr, bytes32 ss) = _signLowS(STOCK_PK, sd);
        vm.prank(bridge);
        lw.attestDelivery(reqId, sr, ss);

        vm.warp(block.timestamp + 601); // past deadline
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, sd);
        vm.prank(bridge);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 8));
        lw.approve(reqId, r, s);
    }

    // =====================================================================
    //  Approval without attestation refused
    // =====================================================================
    function test_approve_without_attestation_refused() public {
        uint32 reqId = 11;
        bytes32 quote = keccak256("q11");
        uint32 deadline = uint32(block.timestamp + 600);
        bytes memory stockIntent = _intent(reqId, 100_000_000, 4, deadline, quote, 0x0001);
        vm.prank(agent);
        lw.propose(stockIntent, "");
        bytes32 sd = _digest(stockIntent);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, sd);
        vm.prank(bridge);
        vm.expectRevert(LastWord.BadState.selector); // still Proposed, not Attested
        lw.approve(reqId, r, s);
    }

    // =====================================================================
    //  Hard criteria at propose: non-whitelisted supplier, over-cap, dup, token
    // =====================================================================
    function test_criterion_non_whitelisted() public {
        uint32 reqId = 20;
        // beneficiary not seeded -> use a fresh address via a tweaked intent
        bytes memory badIntent = abi.encodePacked(
            uint8(1), uint8(1), reqId,
            bytes20(address(0xDEAD)),       // not whitelisted
            uint8(0), uint64(1), uint32(1), uint32(block.timestamp + 600),
            keccak256("q20"), uint16(0x0001), uint16(1)
        );
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 1));
        lw.propose(badIntent, "");
    }

    function test_criterion_over_cap() public {
        uint32 reqId = 21;
        bytes memory badIntent = _intent(reqId, CAP + 1, 1, uint32(block.timestamp + 600), keccak256("q21"), 0x0001);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 3));
        lw.propose(badIntent, "");
    }

    function test_criterion_duplicate_quote() public {
        uint32 reqId = 22;
        bytes32 quote = keccak256("dup");
        bytes memory i1 = _intent(reqId, 1_000_000, 1, uint32(block.timestamp + 600), quote, 0x0001);
        vm.prank(agent);
        lw.propose(i1, "");
        bytes memory i2 = _intent(23, 1_000_000, 2, uint32(block.timestamp + 600), quote, 0x0001);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 6));
        lw.propose(i2, "");
    }

    // =====================================================================
    //  Agent cannot attest or approve (role separation)
    // =====================================================================
    function test_agent_cannot_approve() public {
        uint32 reqId = 30;
        bytes32 digest = _proposeAndAttest(reqId);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, digest);
        vm.prank(agent); // not the bridge
        vm.expectRevert(LastWord.NotAuthorized.selector);
        lw.approve(reqId, r, s);
    }

    // =====================================================================
    //  Pause blocks execution; only admin unpauses
    // =====================================================================
    function test_pause_blocks_and_only_admin_unpauses() public {
        uint32 reqId = 31;
        bytes32 digest = _proposeAndAttest(reqId);
        vm.prank(guardian);
        lw.pause();
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, digest);
        vm.prank(bridge);
        vm.expectRevert(LastWord.IsPaused.selector);
        lw.approve(reqId, r, s);
        // guardian cannot unpause
        vm.prank(guardian);
        vm.expectRevert(LastWord.NotAuthorized.selector);
        lw.unpause();
        // admin can
        vm.prank(admin);
        lw.unpause();
        vm.prank(bridge);
        lw.approve(reqId, r, s);
        assertEq(usd.balanceOf(beneficiary), 250_000_000);
    }

    // =====================================================================
    //  Duress: duress key pays from parallel vault, capped, identical event
    // =====================================================================
    function test_duress_pays_from_parallel_vault_capped() public {
        uint32 reqId = 40;
        bytes32 digest = _proposeAndAttest(reqId);
        // sign with the DURESS key
        (bytes32 r, bytes32 s) = _signLowS(DURESS_PK, digest);
        uint256 vaultBefore = usd.balanceOf(vault);
        uint256 parallelBefore = usd.balanceOf(parallelVault);

        vm.prank(bridge);
        lw.approve(reqId, r, s);

        // real vault untouched
        assertEq(usd.balanceOf(vault), vaultBefore, "real vault must not move");
        // parallel vault paid, capped at PARALLEL_CAP (request was 250M > cap 50M)
        assertEq(parallelBefore - usd.balanceOf(parallelVault), PARALLEL_CAP, "capped decoy payout");
        assertEq(usd.balanceOf(beneficiary), PARALLEL_CAP);
    }

    // =====================================================================
    //  Whitelist timelock + double-sign
    // =====================================================================
    function test_whitelist_timelock_and_double_sign() public {
        address newSup = address(0xBEEF);
        vm.prank(admin);
        lw.proposeWhitelist(newSup, 500_000, true);

        // too early
        vm.prank(coAdmin);
        vm.expectRevert(LastWord.TimelockNotReady.selector);
        lw.applyWhitelist(newSup);

        vm.warp(block.timestamp + DELAY + 1);

        // proposer cannot be the confirmer
        vm.prank(admin);
        vm.expectRevert(LastWord.DoubleSignRequired.selector);
        lw.applyWhitelist(newSup);

        // co-admin confirms
        vm.prank(coAdmin);
        lw.applyWhitelist(newSup);
        (bool active, uint64 cap,) = lw.suppliers(newSup);
        assertTrue(active);
        assertEq(cap, 500_000);
    }
}
