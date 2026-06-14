<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_2f12a932-2240-46a4-b351-2af8f7360401?mode=deep -->
<!-- deepwiki_verdict: needs_local_proof -->

## Verdict
NEEDS_LOCAL_PROOF

## Paid Scope Match
fund_extraction

## Exact Code Path

**file:** `src/BorrowerOperations.sol`
**function:** `openTrove`
**symbols/lines:** lines 269–278 — gasPool receives `systemState.getUSDSGasCompensation()` at open time; trove debt is set to `compositeDebt = netDebt + USDSGasCompensation_at_open`

**file:** `src/TroveManager.sol`
**function:** `_liquidateNormalMode`, `_liquidateRecoveryMode`
**symbols/lines:** lines 181, 234 — `singleLiquidation.USDSGasCompensation = systemState.getUSDSGasCompensation()` reads the **current** value, not the value stored in the trove's debt

**file:** `src/TroveManager.sol`
**function:** `_sendGasCompensation`
**symbols/lines:** lines 836–837 — `usdsToken.returnFromPool(gasPoolAddress, _liquidator, _USDS)` transfers the current-value amount with no per-trove deposit check

**file:** `src/SystemState.sol`
**function:** `setUSDSGasCompensation`
**symbols/lines:** lines 64–66 — timelock can change `USDSGasCompensation` at any time with no migration of existing trove accounting

---

**Root cause:** The gasPool is a shared, untracked pool. Each trove deposits `USDSGasCompensation_at_open` into it, but liquidation always withdraws `USDSGasCompensation_current`. There is no per-trove record of how much was deposited, and no invariant check that `totalUSDSGasCompensation_to_send ≤ gasPool.balance`. If the timelock raises `USDSGasCompensation` between trove openings and liquidation, liquidating old troves draws more USDS from the gasPool than those troves deposited, consuming deposits that belong to newer troves. [1](#0-0) [2](#0-1) [3](#0-2) [4](#0-3) 

## Attacker Path

**preconditions:**
1. Timelock raises `USDSGasCompensation` from `OLD` (e.g. 10e18) to `NEW` (e.g. 20e18) via `SystemState.setUSDSGasCompensation`.
2. After the change, M new troves are opened, each depositing `NEW` into the gasPool. gasPool balance = `N*OLD + M*NEW`.
3. N old troves (opened before the change, each depositing `OLD`) become undercollateralized (price drop).

**attacker-controlled inputs:**
- `_troveArray` in `batchLiquidateTroves` — the liquidator selects the N old troves.

**call sequence:**
1. `SystemState.setUSDSGasCompensation(NEW)` — timelock (privileged prerequisite).
2. M borrowers call `openTrove(...)` — each mints `NEW` USDS to gasPool.
3. Price drops; N old troves fall below MCR.
4. Liquidator calls `batchLiquidateTroves([old_trove_1, ..., old_trove_N], ...)`.
5. Each `_liquidateNormalMode` sets `singleLiquidation.USDSGasCompensation = NEW`.
6. `totals.totalUSDSGasCompensation = N * NEW`.
7. `_sendGasCompensation` calls `usdsToken.returnFromPool(gasPoolAddress, liquidator, N*NEW)`.
8. gasPool has `N*OLD + M*NEW ≥ N*NEW` (if M is large enough), so transfer succeeds.
9. Liquidator receives `N*NEW`; only `N*OLD` was deposited for those troves. Excess = `N*(NEW-OLD)`. [5](#0-4) [6](#0-5) 

## Why Existing Checks Fail

- `_sendGasCompensation` performs no balance check on `gasPoolAddress` before calling `returnFromPool`. [7](#0-6) 
- `_addLiquidationValuesToTotals` blindly accumulates `singleLiquidation.USDSGasCompensation` (current value) without reference to what each trove actually deposited. [8](#0-7) 
- The trove struct stores `compositeDebt` (which embeds `USDSGasCompensation_at_open`) but this stored value is never consulted during liquidation to determine the gas compensation amount — only `systemState.getUSDSGasCompensation()` is used. [9](#0-8) 
- `SystemState.setUSDSGasCompensation` has no migration logic, no cap relative to existing trove deposits, and no event-driven rebalancing of the gasPool. [10](#0-9) 
- `GasPool` is a passive contract with no accounting — it cannot enforce per-trove withdrawal limits. [11](#0-10) 

## Rejection Checks

**expected behavior checked:** Liquity's original design assumes `USDS_GAS_COMPENSATION` is a compile-time constant. Sable made it a mutable timelock parameter without updating the liquidation path to use the per-trove stored value. This is not expected behavior — it is a design gap introduced by the mutability change.

**prior report checked:** No evidence in the indexed codebase of a prior report covering this specific root cause (mutable `USDSGasCompensation` + shared gasPool + no per-trove deposit tracking).

**README/NatSpec checked:** `GasPool.sol` NatSpec still references the original fixed "50 USDS" assumption, confirming the mutability was not accounted for in the pool design. [12](#0-11) 

**unsupported assumption checked:** The exploit requires the timelock to raise `USDSGasCompensation`. This is a privileged action, but the rules permit it as a prerequisite when it creates a later user-triggered extraction path. The liquidator's call to `batchLiquidateTroves` is fully unprivileged.

## Local Proof Required

**test type:** Foundry integration test

**test file to add:** `test/GasPoolMismatch.t.sol`

**test setup:**
1. Deploy full protocol stack (SystemState, BorrowerOperations, TroveManager, USDSToken, GasPool, ActivePool, etc.).
2. Set `USDSGasCompensation = 10e18`.
3. Open N=5 troves (old borrowers), each depositing 10e18 into gasPool. gasPool balance = 50e18.
4. Call `SystemState.setUSDSGasCompensation(20e18)` via timelock.
5. Open M=5 new troves, each depositing 20e18 into gasPool. gasPool balance = 150e18.
6. Drop price so old 5 troves fall below MCR.
7. Record `gasPoolBalanceBefore = usdsToken.balanceOf(gasPoolAddress)` and `liquidatorBalanceBefore`.

**call sequence:** `batchLiquidateTroves([old_trove_1..5], ...)` by unprivileged liquidator.

**expected assertion:**
```solidity
// Liquidator received N*NEW = 5*20e18 = 100e18
assertEq(usdsToken.balanceOf(liquidator) - liquidatorBalanceBefore, 100e18);
// But old troves only deposited N*OLD = 5*10e18 = 50e18
// Excess extracted from new troves' deposits:
assertEq(gasPoolBalanceBefore - usdsToken.balanceOf(gasPoolAddress), 100e18);
// New troves' gasPool entitlement is now underfunded by 50e18
```

**failure condition:** If `returnFromPool` reverts (gasPool balance insufficient) or if the liquidator receives exactly `N*OLD`, the vulnerability does not hold under those conditions. The test must confirm the shared-pool balance is sufficient for the transfer to succeed and that the liquidator receives the inflated amount.

### Citations

**File:** src/BorrowerOperations.sol (L213-214)
```text
        vars.compositeDebt = _getCompositeDebt(vars.netDebt);
        assert(vars.compositeDebt > 0);
```

**File:** src/BorrowerOperations.sol (L269-278)
```text
            uint USDS_GAS_COMPENSATION = systemState.getUSDSGasCompensation();

            WithdrawUSDSParam memory withdrawParam2 = WithdrawUSDSParam({
                activePool: contractsCache.activePool,
                usdsToken: contractsCache.usdsToken,
                account: gasPoolAddress,
                USDSAmount: USDS_GAS_COMPENSATION,
                netDebtIncrease: USDS_GAS_COMPENSATION
            });
            _withdrawUSDS(withdrawParam2);
```

**File:** src/TroveManager.sol (L178-182)
```text
        singleLiquidation.collGasCompensation = _getCollGasCompensation(
            singleLiquidation.entireTroveColl
        );
        singleLiquidation.USDSGasCompensation = systemState.getUSDSGasCompensation();
        uint collToLiquidate = singleLiquidation.entireTroveColl.sub(
```

**File:** src/TroveManager.sol (L460-465)
```text
        _sendGasCompensation(
            contractsCache.activePool,
            msg.sender,
            totals.totalUSDSGasCompensation,
            totals.totalCollGasCompensation
        );
```

**File:** src/TroveManager.sol (L800-806)
```text
        // Tally all the values with their respective running totals
        newTotals.totalCollGasCompensation = oldTotals.totalCollGasCompensation.add(
            singleLiquidation.collGasCompensation
        );
        newTotals.totalUSDSGasCompensation = oldTotals.totalUSDSGasCompensation.add(
            singleLiquidation.USDSGasCompensation
        );
```

**File:** src/TroveManager.sol (L830-843)
```text
    function _sendGasCompensation(
        IActivePool _activePool,
        address _liquidator,
        uint _USDS,
        uint _BNB
    ) internal {
        if (_USDS > 0) {
            usdsToken.returnFromPool(gasPoolAddress, _liquidator, _USDS);
        }

        if (_BNB > 0) {
            _activePool.sendBNB(_liquidator, _BNB);
        }
    }
```

**File:** src/SystemState.sol (L64-66)
```text
    function setUSDSGasCompensation(uint _value) external override onlyTimeLock {
        _setUSDSGasCompensation(_value);
    }
```

**File:** src/SystemState.sol (L113-117)
```text
     function _setUSDSGasCompensation(uint _value) internal {
        uint oldValue = USDSGasCompensation;
        USDSGasCompensation = _value;
        emit USDSGasCompensationChanged(oldValue, _value);
    }
```

**File:** src/GasPool.sol (L7-15)
```text
 * The purpose of this contract is to hold USDS tokens for gas compensation:
 * https://github.com/liquity/dev#gas-compensation
 * When a borrower opens a trove, an additional 50 USDS debt is issued,
 * and 50 USDS is minted and sent to this contract.
 * When a borrower closes their active trove, this gas compensation is refunded:
 * 50 USDS is burned from the this contract's balance, and the corresponding
 * 50 USDS debt on the trove is cancelled.
 * See this issue for more context: https://github.com/liquity/dev/issues/186
 */
```

**File:** src/GasPool.sol (L16-18)
```text
contract GasPool {
    // do nothing, as the core contracts have permission to send to and burn from this address
}
```
