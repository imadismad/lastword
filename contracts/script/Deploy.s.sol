// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {LastWord} from "../src/LastWord.sol";
import {DemoUSD} from "../src/DemoUSD.sol";

/// @notice Deploys DemoUSD + LastWord, wires roles, and registers badge pubkeys read
///         from badge_pubkeys.json (via env). Run against anvil or the Avalanche L1.
///
/// Required env:
///   PRIVATE_KEY             deployer (becomes admin)
///   AGENT_ADDR, BRIDGE_ADDR, GUARDIAN_ADDR, COADMIN_ADDR, REQUESTER_ADDR
///   DAF_QX, DAF_QY          DAF P-256 pubkey (bytes32 hex)
///   STOCK_QX, STOCK_QY      stock P-256 pubkey
///   DURESS_QX, DURESS_QY    duress P-256 pubkey (optional, 0 if absent)
///   SUPPLIER_ADDR, SUPPLIER_CAP   demo supplier to seed
contract Deploy is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(pk);

        DemoUSD usd = new DemoUSD();
        address deployer = vm.addr(pk);

        // vault = deployer for the demo; parallelVault is a separate decoy account.
        address vault = deployer;
        address parallelVault = vm.envOr("PARALLEL_VAULT", deployer);
        uint64 parallelCap = uint64(vm.envOr("PARALLEL_CAP", uint256(50_000_000)));
        uint64 whitelistDelay = uint64(vm.envOr("WHITELIST_DELAY", uint256(60)));

        LastWord lw = new LastWord(usd, vault, parallelVault, parallelCap, whitelistDelay);

        lw.setRoles(
            vm.envAddress("AGENT_ADDR"),
            vm.envOr("REQUESTER_ADDR", address(0)),
            vm.envOr("COADMIN_ADDR", address(0)),
            vm.envOr("GUARDIAN_ADDR", address(0)),
            vm.envAddress("BRIDGE_ADDR")
        );

        lw.registerDafKey(vm.envBytes32("DAF_QX"), vm.envBytes32("DAF_QY"));
        lw.registerStockKey(vm.envBytes32("STOCK_QX"), vm.envBytes32("STOCK_QY"));
        lw.registerDuressKey(
            vm.envOr("DURESS_QX", bytes32(0)),
            vm.envOr("DURESS_QY", bytes32(0))
        );

        // seed demo supplier + fund vaults
        address supplier = vm.envOr("SUPPLIER_ADDR", address(0));
        if (supplier != address(0)) {
            uint64 cap = uint64(vm.envOr("SUPPLIER_CAP", uint256(1_000_000_000)));
            lw.seedSupplierForDemo(supplier, cap, whitelistDelay + 1);
        }
        usd.mint(vault, 1_000_000_000_000);
        usd.approve(address(lw), type(uint256).max);
        if (parallelVault == deployer) {
            // same account; already approved and funded
        }

        vm.stopBroadcast();

        console.log("DemoUSD:", address(usd));
        console.log("LastWord:", address(lw));
    }
}
