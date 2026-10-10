// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {LastWord} from "../src/LastWord.sol";
import {DemoUSD} from "../src/DemoUSD.sol";
import {P256} from "@openzeppelin/contracts/utils/cryptography/P256.sol";

contract LastWordTest is Test {
    LastWord lw;
    DemoUSD usd;

    address admin = address(0xA11CE);
    address coAdmin = address(0xC0ADA);
    address agent = address(0xA6E17);
    address bridge = address(0xB41D6E);
    address guardian = address(0x6DA12);
    address beneficiary = address(0x1111111111111111111111111111111111111111);
    address vault = address(0x7A017);
    address parallelVault = address(0xDEC00);

    uint256 constant DAF_PK = 0xC001;
    uint256 constant STOCK_PK = 0x57C0;
    uint256 constant DURESS_PK = 0xD12E55;

    uint64 constant CAP = 1_000_000_000;
    uint64 constant DELAY = 1 days;
    uint64 constant PARALLEL_CAP = 50_000_000;

    uint256 constant P256_N =
        0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551;

    uint16 constant ROLE_STOCK = 0x0001;
    uint16 constant ROLE_DAF = 0x0002;

    function setUp() public {
        vm.warp(10_000_000);
        usd = new DemoUSD();

        vm.prank(admin);
        lw = new LastWord(usd, vault, parallelVault, PARALLEL_CAP, DELAY);

        vm.prank(admin);
        lw.setRoles(agent, address(0), coAdmin, guardian, bridge);

        (uint256 dqx, uint256 dqy) = vm.publicKeyP256(DAF_PK);
        (uint256 sqx, uint256 sqy) = vm.publicKeyP256(STOCK_PK);
        (uint256 uqx, uint256 uqy) = vm.publicKeyP256(DURESS_PK);
        vm.startPrank(admin);
        lw.registerDafKey(bytes32(dqx), bytes32(dqy));
        lw.registerStockKey(bytes32(sqx), bytes32(sqy));
        lw.registerDuressKey(bytes32(uqx), bytes32(uqy));
        lw.seedSupplierForDemo(beneficiary, CAP, DELAY + 1);
        vm.stopPrank();

        usd.mint(vault, 1_000_000_000_000);
        usd.mint(parallelVault, 1_000_000_000_000);
        vm.prank(vault);
        usd.approve(address(lw), type(uint256).max);
        vm.prank(parallelVault);
        usd.approve(address(lw), type(uint256).max);
    }

    // --------------------------------------------------------- intent builder
    function _intent(
        uint32 reqId, uint64 amount, uint32 nonce, uint32 deadline,
        bytes32 quoteHash, uint16 flags
    ) internal view returns (bytes memory) {
        return abi.encodePacked(
            uint8(1), uint8(1), reqId, bytes20(beneficiary), uint8(0),
            amount, nonce, deadline, quoteHash, flags, uint16(1)
        );
    }

    function _digest(bytes memory intent) internal view returns (bytes32) {
        return sha256(abi.encodePacked(
            bytes11("LASTWORD-v1"), uint64(block.chainid), address(lw), intent));
    }

    function _signLowS(uint256 pk, bytes32 digest) internal pure returns (bytes32 r, bytes32 s) {
        (r, s) = vm.signP256(pk, digest);
        if (uint256(s) > P256_N / 2) s = bytes32(P256_N - uint256(s));
    }

    // Propose a DAF intent, then attest with the matching STOCK intent (same economics).
    // Returns the stored (DAF) intent bytes for the later approve call.
    function _proposeAndAttest(uint32 reqId, uint64 amount)
        internal
        returns (bytes memory dafIntent)
    {
        bytes32 quote = keccak256(abi.encodePacked("quote", reqId));
        uint32 deadline = uint32(block.timestamp + 600);

        dafIntent = _intent(reqId, amount, 7, deadline, quote, ROLE_DAF);
        vm.prank(agent);
        lw.propose(dafIntent, "");

        bytes memory stockIntent = _intent(reqId, amount, 7, deadline, quote, ROLE_STOCK);
        (bytes32 sr, bytes32 ss) = _signLowS(STOCK_PK, _digest(stockIntent));
        vm.prank(bridge);
        lw.attestDelivery(reqId, stockIntent, sr, ss);
    }

    // ===================================================== T-01: P-256 verify
    function test_T01_p256_low_s_accepted_high_s_rejected() public view {
        bytes32 h = sha256("lastword-test");
        (uint256 qx, uint256 qy) = vm.publicKeyP256(DAF_PK);
        (bytes32 r, bytes32 s) = vm.signP256(DAF_PK, h);
        bytes32 sLow = uint256(s) > P256_N / 2 ? bytes32(P256_N - uint256(s)) : s;
        bytes32 sHigh = bytes32(P256_N - uint256(sLow));
        assertTrue(P256.verify(h, r, sLow, bytes32(qx), bytes32(qy)), "low-s verifies");
        assertFalse(P256.verify(h, r, sHigh, bytes32(qx), bytes32(qy)), "high-s rejected");
    }

    // ===================================================== nominal payment
    function test_nominal_payment() public {
        uint32 reqId = 1;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        uint256 before = usd.balanceOf(beneficiary);
        vm.prank(bridge);
        lw.approve(reqId, dafIntent, r, s);
        assertEq(usd.balanceOf(beneficiary) - before, 250_000_000);
    }

    // ===================================================== forged key refused
    function test_forged_signature_refused() public {
        uint32 reqId = 2;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        // sign the DAF digest with the STOCK key -> fails under DAF/duress pubkeys
        (bytes32 r, bytes32 s) = _signLowS(STOCK_PK, _digest(dafIntent));
        vm.prank(bridge);
        vm.expectRevert(LastWord.BadSignature.selector);
        lw.approve(reqId, dafIntent, r, s);
    }

    // ===================================================== tampered intent refused
    function test_tampered_amount_refused() public {
        uint32 reqId = 3;
        _proposeAndAttest(reqId, 250_000_000);
        // approve with a DAF intent whose amount differs from the stored request
        bytes32 quote = keccak256(abi.encodePacked("quote", reqId));
        bytes memory tampered = _intent(reqId, 999_000_000, 7,
            uint32(block.timestamp + 600), quote, ROLE_DAF);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(tampered));
        vm.prank(bridge);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 7));
        lw.approve(reqId, tampered, r, s);
    }

    // ===================================================== replay nonce refused
    function test_replay_nonce_refused() public {
        uint32 reqId = 4;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        vm.prank(bridge);
        lw.approve(reqId, dafIntent, r, s);

        // second request reusing nonce 7 must be refused at approve
        uint32 reqId2 = 6;
        bytes32 quote = keccak256(abi.encodePacked("replay", reqId2));
        uint32 deadline = uint32(block.timestamp + 600);
        bytes memory daf2 = _intent(reqId2, 100_000_000, 7, deadline, quote, ROLE_DAF);
        vm.prank(agent);
        lw.propose(daf2, "");
        bytes memory stock2 = _intent(reqId2, 100_000_000, 7, deadline, quote, ROLE_STOCK);
        (bytes32 sr, bytes32 ss) = _signLowS(STOCK_PK, _digest(stock2));
        vm.prank(bridge);
        lw.attestDelivery(reqId2, stock2, sr, ss);
        (bytes32 r2, bytes32 s2) = _signLowS(DAF_PK, _digest(daf2));
        vm.prank(bridge);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 99));
        lw.approve(reqId2, daf2, r2, s2);
    }

    // ===================================================== expired refused
    function test_expired_refused() public {
        uint32 reqId = 10;
        bytes memory dafIntent = _proposeAndAttest(reqId, 100_000_000);
        vm.warp(block.timestamp + 601);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        vm.prank(bridge);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 8));
        lw.approve(reqId, dafIntent, r, s);
    }

    // ===================================================== approve w/o attestation
    function test_approve_without_attestation_refused() public {
        uint32 reqId = 11;
        bytes32 quote = keccak256("q11");
        uint32 deadline = uint32(block.timestamp + 600);
        bytes memory dafIntent = _intent(reqId, 100_000_000, 4, deadline, quote, ROLE_DAF);
        vm.prank(agent);
        lw.propose(dafIntent, "");
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        vm.prank(bridge);
        vm.expectRevert(LastWord.BadState.selector); // still Proposed
        lw.approve(reqId, dafIntent, r, s);
    }

    // ===================================================== hard criteria at propose
    function test_criterion_non_whitelisted() public {
        bytes memory bad = abi.encodePacked(
            uint8(1), uint8(1), uint32(20), bytes20(address(0xDEAD)), uint8(0),
            uint64(1), uint32(1), uint32(block.timestamp + 600),
            keccak256("q20"), ROLE_DAF, uint16(1));
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 1));
        lw.propose(bad, "");
    }

    function test_criterion_over_cap() public {
        bytes memory bad = _intent(21, CAP + 1, 1, uint32(block.timestamp + 600),
            keccak256("q21"), ROLE_DAF);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 3));
        lw.propose(bad, "");
    }

    function test_criterion_duplicate_quote() public {
        bytes32 quote = keccak256("dup");
        bytes memory i1 = _intent(22, 1_000_000, 1, uint32(block.timestamp + 600), quote, ROLE_DAF);
        vm.prank(agent);
        lw.propose(i1, "");
        bytes memory i2 = _intent(23, 1_000_000, 2, uint32(block.timestamp + 600), quote, ROLE_DAF);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(LastWord.HardCriterion.selector, 6));
        lw.propose(i2, "");
    }

    // ===================================================== role separation (caller)
    function test_agent_cannot_approve() public {
        uint32 reqId = 30;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        vm.prank(agent);
        vm.expectRevert(LastWord.NotAuthorized.selector);
        lw.approve(reqId, dafIntent, r, s);
    }

    // ===================================================== pause / unpause
    function test_pause_blocks_and_only_admin_unpauses() public {
        uint32 reqId = 31;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        vm.prank(guardian);
        lw.pause();
        (bytes32 r, bytes32 s) = _signLowS(DAF_PK, _digest(dafIntent));
        vm.prank(bridge);
        vm.expectRevert(LastWord.IsPaused.selector);
        lw.approve(reqId, dafIntent, r, s);
        vm.prank(guardian);
        vm.expectRevert(LastWord.NotAuthorized.selector);
        lw.unpause();
        vm.prank(admin);
        lw.unpause();
        vm.prank(bridge);
        lw.approve(reqId, dafIntent, r, s);
        assertEq(usd.balanceOf(beneficiary), 250_000_000);
    }

    // ===================================================== duress
    function test_duress_pays_from_parallel_vault_capped() public {
        uint32 reqId = 40;
        bytes memory dafIntent = _proposeAndAttest(reqId, 250_000_000);
        (bytes32 r, bytes32 s) = _signLowS(DURESS_PK, _digest(dafIntent));
        uint256 vaultBefore = usd.balanceOf(vault);
        uint256 parBefore = usd.balanceOf(parallelVault);
        vm.prank(bridge);
        lw.approve(reqId, dafIntent, r, s);
        assertEq(usd.balanceOf(vault), vaultBefore, "real vault untouched");
        assertEq(parBefore - usd.balanceOf(parallelVault), PARALLEL_CAP, "capped decoy");
        assertEq(usd.balanceOf(beneficiary), PARALLEL_CAP);
    }

    // ===================================================== whitelist timelock + 2-sig
    function test_whitelist_timelock_and_double_sign() public {
        address newSup = address(0xBEEF);
        vm.prank(admin);
        lw.proposeWhitelist(newSup, 500_000, true);
        vm.prank(coAdmin);
        vm.expectRevert(LastWord.TimelockNotReady.selector);
        lw.applyWhitelist(newSup);
        vm.warp(block.timestamp + DELAY + 1);
        vm.prank(admin);
        vm.expectRevert(LastWord.DoubleSignRequired.selector);
        lw.applyWhitelist(newSup);
        vm.prank(coAdmin);
        lw.applyWhitelist(newSup);
        (bool active, uint64 cap,) = lw.suppliers(newSup);
        assertTrue(active);
        assertEq(cap, 500_000);
    }
}
