// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {P256} from "@openzeppelin/contracts/utils/cryptography/P256.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @title LASTWORD payment authority
/// @notice The contract is the ONLY authority. It applies the hard criteria,
///         requires three distinct signatures (agent proposes, requester attests
///         delivery, DAF approves with a P-256 badge signature) and only executes
///         what has been cryptographically proven. See cahier des charges s6, s10, s11.
///
/// Digest (must match proto/SPEC.md I1 and lastword_proto exactly):
///   digest = SHA-256( "LASTWORD-v1" || chainId(8 BE) || contractAddr(20) || intent(79) )
contract LastWord {
    // --------------------------------------------------------------------- types
    enum State { None, Proposed, Attested, Approved, Refused, Cancelled, Expired }

    struct Request {
        State state;
        address beneficiary;
        uint8 token;
        uint64 amount;
        uint32 nonce;
        uint32 deadline;
        bytes32 quoteHash;
        bytes32 digest;      // the recomputed digest the badge must sign
        uint16 flags;
        uint16 policy;
        bool duress;         // internal only - never exposed in events
    }

    struct Supplier {
        bool active;
        uint64 cap;          // per-transaction cap (token smallest unit)
        uint64 registeredAt; // for the ageing criterion C2
    }

    struct WhitelistChange {
        uint64 cap;
        bool active;
        uint64 readyAt;      // timelock: not applicable before this time
        address proposer;    // double-sig: a different admin must confirm
        bool exists;
    }

    // --------------------------------------------------------------------- roles
    address public agent;        // proposes only
    address public requester;    // attests delivery (EVM key, distinct from DAF)
    address public admin;        // whitelist / unpause / rotate
    address public coAdmin;      // second admin for double-sig whitelist changes
    address public guardian;     // can pause, cannot unpause
    address public bridge;       // submits txs, pays gas, approves nothing

    // DAF P-256 public keys (registered under one approver identity)
    bytes32 public dafQx;
    bytes32 public dafQy;
    bytes32 public duressQx;
    bytes32 public duressQy;
    // STOCK P-256 public key (delivery attestation)
    bytes32 public stockQx;
    bytes32 public stockQy;

    // --------------------------------------------------------------------- config
    IERC20 public immutable token0;    // demo stablecoin
    address public vault;              // real funds source
    address public parallelVault;      // duress decoy source
    uint64 public parallelCap;         // fixed cap, independent of the request

    uint64 public whitelistDelay;      // timelock duration (C2 / FR-04)
    uint256 public anchoredRoot;       // last anchored journal root (as uint for event)

    bool public paused;

    mapping(uint32 => Request) public requests;
    mapping(address => Supplier) public suppliers;
    mapping(bytes32 => bool) public usedQuoteHash;    // C6 duplicate
    mapping(uint32 => bool) public usedNonce;         // approver nonce anti-replay
    mapping(address => WhitelistChange) public pendingWhitelist;

    uint8 public constant ALLOWED_TOKEN = 0;          // only token index 0 (C9)

    // ------------------------------------------------------------------- events
    event Proposed(uint32 indexed reqId, bytes32 digest);
    event Attested(uint32 indexed reqId);
    event Approved(uint32 indexed reqId, address beneficiary, uint256 amount);
    event Refused(uint32 indexed reqId, uint8 reason);
    event Cancelled(uint32 indexed reqId);
    event Anchored(bytes32 root);
    event Paused();
    event Unpaused();
    event WhitelistProposed(address indexed supplier, uint64 cap, bool active, uint64 readyAt);
    event WhitelistApplied(address indexed supplier, uint64 cap, bool active);

    // ------------------------------------------------------------------- errors
    error NotAuthorized();
    error IsPaused();
    error BadState();
    error HardCriterion(uint8 code);
    error BadSignature();
    error TimelockNotReady();
    error DoubleSignRequired();

    // ----------------------------------------------------------------- modifiers
    modifier onlyBridge() { if (msg.sender != bridge) revert NotAuthorized(); _; }
    modifier onlyAgent()  { if (msg.sender != agent)  revert NotAuthorized(); _; }
    modifier onlyAdmin()  { if (msg.sender != admin)  revert NotAuthorized(); _; }
    modifier notPaused()  { if (paused) revert IsPaused(); _; }

    constructor(
        IERC20 _token0,
        address _vault,
        address _parallelVault,
        uint64 _parallelCap,
        uint64 _whitelistDelay
    ) {
        token0 = _token0;
        vault = _vault;
        parallelVault = _parallelVault;
        parallelCap = _parallelCap;
        whitelistDelay = _whitelistDelay;
        admin = msg.sender;
    }

    // -------------------------------------------------------------- role wiring
    function setRoles(
        address _agent, address _requester, address _coAdmin,
        address _guardian, address _bridge
    ) external onlyAdmin {
        agent = _agent;
        requester = _requester;
        coAdmin = _coAdmin;
        guardian = _guardian;
        bridge = _bridge;
    }

    function registerDafKey(bytes32 qx, bytes32 qy) external onlyAdmin { dafQx = qx; dafQy = qy; }
    function registerDuressKey(bytes32 qx, bytes32 qy) external onlyAdmin { duressQx = qx; duressQy = qy; }
    function registerStockKey(bytes32 qx, bytes32 qy) external onlyAdmin { stockQx = qx; stockQy = qy; }

    // ------------------------------------------------------------ digest (I1)
    /// @dev Recomputes the canonical digest from the 79-byte intent. The contract
    ///      NEVER trusts a digest from input; it recomputes from the parameters it
    ///      will execute. One differing byte invalidates the badge signature.
    function computeDigest(bytes calldata intent) public view returns (bytes32) {
        require(intent.length == 79, "intent!=79");
        return sha256(
            abi.encodePacked(
                bytes11("LASTWORD-v1"),
                uint64(block.chainid),
                address(this),
                intent
            )
        );
    }

    // ------------------------------------------------- intent field decoding
    // Layout (big-endian), see proto I1:
    // [0]ver [1]algo [2:6]reqId [6:26]beneficiary [26]token
    // [27:35]amount [35:39]nonce [39:43]deadline [43:75]quoteHash [75:77]flags [77:79]policy
    function _decode(bytes calldata intent) internal pure returns (Request memory r) {
        r.beneficiary = address(bytes20(intent[6:26]));
        r.token       = uint8(intent[26]);
        r.amount      = uint64(bytes8(intent[27:35]));
        r.nonce       = uint32(bytes4(intent[35:39]));
        r.deadline    = uint32(bytes4(intent[39:43]));
        r.quoteHash   = bytes32(intent[43:75]);
        r.flags       = uint16(bytes2(intent[75:77]));
        r.policy      = uint16(bytes2(intent[77:79]));
    }

    function _reqId(bytes calldata intent) internal pure returns (uint32) {
        return uint32(bytes4(intent[2:6]));
    }

    /// @dev The stock and DAF intents for a reqId may differ only in role bits (flags
    ///      bits 0-1) and nonce. All economic fields must equal the stored request,
    ///      so a signature cannot be redirected to a different beneficiary/amount/quote.
    function _requireSameEconomics(Request storage req, bytes calldata intent, uint32 reqId)
        internal
        view
    {
        require(intent.length == 79, "intent!=79");
        if (_reqId(intent) != reqId) revert HardCriterion(7);
        Request memory d = _decode(intent);
        if (d.beneficiary != req.beneficiary) revert HardCriterion(7);
        if (d.token != req.token) revert HardCriterion(7);
        if (d.amount != req.amount) revert HardCriterion(7);
        if (d.quoteHash != req.quoteHash) revert HardCriterion(7);
        if (d.deadline != req.deadline) revert HardCriterion(7);
    }

    // --------------------------------------------------------------- STEP 1
    /// @notice Agent proposes. Enforces hard criteria C1,C3,C6,C8,C9 on-chain.
    ///         (C11-C13 are off-chain and ride in the agent's signed verdict/flags.)
    function propose(bytes calldata intent, bytes calldata /*proofs*/)
        external
        onlyAgent
        notPaused
        returns (uint32 reqId)
    {
        reqId = _reqId(intent);
        if (requests[reqId].state != State.None) revert BadState();

        Request memory r = _decode(intent);
        r.digest = computeDigest(intent);
        r.state = State.Proposed;

        // C9 allowed token
        if (r.token != ALLOWED_TOKEN) revert HardCriterion(9);
        // C1 supplier whitelisted & active
        Supplier memory sup = suppliers[r.beneficiary];
        if (!sup.active) revert HardCriterion(1);
        // C3 per-transaction cap
        if (r.amount > sup.cap) revert HardCriterion(3);
        // C2 ageing: supplier must have been registered long enough
        if (block.timestamp < uint256(sup.registeredAt) + whitelistDelay) revert HardCriterion(2);
        // C6 duplicate quote
        if (usedQuoteHash[r.quoteHash]) revert HardCriterion(6);
        // C8 validity (deadline in the future)
        if (r.deadline <= block.timestamp) revert HardCriterion(8);

        usedQuoteHash[r.quoteHash] = true;
        requests[reqId] = r;
        emit Proposed(reqId, r.digest);
    }

    // --------------------------------------------------------------- STEP 2
    /// @notice Requester attests delivery. The caller supplies the STOCK intent (role
    ///         bits 01); the contract recomputes its digest and checks it binds to the
    ///         same economic fields as the proposed request, then verifies the STOCK
    ///         P-256 signature. Role separation is enforced by WHICH key signs.
    function attestDelivery(uint32 reqId, bytes calldata stockIntent, bytes32 r_, bytes32 s_)
        external
        onlyBridge
        notPaused
    {
        Request storage req = requests[reqId];
        if (req.state != State.Proposed) revert BadState();
        _requireSameEconomics(req, stockIntent, reqId);
        bytes32 dg = computeDigest(stockIntent);
        if (!P256.verify(dg, r_, s_, stockQx, stockQy)) revert BadSignature();
        req.state = State.Attested;
        emit Attested(reqId);
    }

    // --------------------------------------------------------------- STEP 3
    /// @notice DAF approves. The caller supplies the DAF intent (role bits 10); the
    ///         contract recomputes its digest, checks it binds to the same economic
    ///         fields, then tries the DAF key then the duress key (at most two
    ///         verifications). On duress it pays from the capped parallel vault; the
    ///         public event is identical.
    function approve(uint32 reqId, bytes calldata dafIntent, bytes32 r_, bytes32 s_)
        external
        onlyBridge
        notPaused
    {
        Request storage req = requests[reqId];
        if (req.state != State.Attested) revert BadState();           // C10 delivery first
        if (req.deadline <= block.timestamp) {                        // C8 expiry
            req.state = State.Expired;
            emit Refused(reqId, 8);
            revert HardCriterion(8);
        }
        if (usedNonce[req.nonce]) revert HardCriterion(99);           // anti-replay
        _requireSameEconomics(req, dafIntent, reqId);
        bytes32 dg = computeDigest(dafIntent);

        // Role separation enforced by WHICH key signs (DAF or duress pubkey).
        bool normal = P256.verify(dg, r_, s_, dafQx, dafQy);
        bool isDuress = false;
        if (!normal) {
            isDuress = P256.verify(req.digest, r_, s_, duressQx, duressQy);
            if (!isDuress) revert BadSignature();
        }

        usedNonce[req.nonce] = true;
        req.duress = isDuress;
        req.state = State.Approved;

        address src;
        uint256 amt;
        if (isDuress) {
            src = parallelVault;
            amt = req.amount <= parallelCap ? req.amount : parallelCap; // fixed cap
        } else {
            src = vault;
            amt = req.amount;
        }
        // Pull from the chosen vault (vault must approve this contract).
        require(token0.transferFrom(src, req.beneficiary, amt), "transfer failed");

        // Public event identical in both cases (no duress leakage).
        emit Approved(reqId, req.beneficiary, amt);
    }

    // ------------------------------------------------------------- lifecycle
    function cancel(uint32 reqId) external {
        if (msg.sender != admin && msg.sender != bridge) revert NotAuthorized();
        Request storage req = requests[reqId];
        if (req.state != State.Proposed && req.state != State.Attested) revert BadState();
        req.state = State.Cancelled;
        emit Cancelled(reqId);
    }

    function pause() external {
        if (msg.sender != guardian && msg.sender != admin) revert NotAuthorized();
        paused = true;
        emit Paused();
    }

    function unpause() external onlyAdmin {
        paused = false;
        emit Unpaused();
    }

    function anchor(bytes32 root) external {
        if (msg.sender != bridge && msg.sender != admin) revert NotAuthorized();
        anchoredRoot = uint256(root);
        emit Anchored(root);
    }

    // ------------------------------------------------- whitelist (timelock + 2-sig)
    /// @notice First admin proposes a whitelist change; it becomes applicable only
    ///         after the timelock and must be confirmed by the co-admin (double sig).
    function proposeWhitelist(address supplier, uint64 cap, bool active) external onlyAdmin {
        pendingWhitelist[supplier] = WhitelistChange({
            cap: cap,
            active: active,
            readyAt: uint64(block.timestamp) + whitelistDelay,
            proposer: msg.sender,
            exists: true
        });
        emit WhitelistProposed(supplier, cap, active, uint64(block.timestamp) + whitelistDelay);
    }

    /// @notice Co-admin confirms after the timelock. A different key than the proposer.
    function applyWhitelist(address supplier) external {
        WhitelistChange memory c = pendingWhitelist[supplier];
        if (!c.exists) revert BadState();
        if (msg.sender != coAdmin) revert DoubleSignRequired();
        if (msg.sender == c.proposer) revert DoubleSignRequired();
        if (block.timestamp < c.readyAt) revert TimelockNotReady();

        Supplier storage s = suppliers[supplier];
        if (s.registeredAt == 0) s.registeredAt = uint64(block.timestamp);
        s.cap = c.cap;
        s.active = c.active;
        delete pendingWhitelist[supplier];
        emit WhitelistApplied(supplier, c.cap, c.active);
    }

    // Demo convenience: seed a supplier immediately with a backdated registration so
    // tests/demo don't wait out the timelock. Admin only; clearly not for production.
    function seedSupplierForDemo(address supplier, uint64 cap, uint64 ageSeconds) external onlyAdmin {
        suppliers[supplier] = Supplier({
            active: true,
            cap: cap,
            registeredAt: uint64(block.timestamp) - ageSeconds
        });
    }
}
