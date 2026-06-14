<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_b654abf8-4261-4020-b743-f9e410ac9623?mode=deep -->
<!-- deepwiki_verdict: high_confidence_candidate -->

I have all the code I need. Let me analyze the exact mechanics.

**Key code paths confirmed:**

`hasPendingRewards` only checks the BNB accumulator: [1](#0-0) 

`_applyPendingRewards` is entirely gated on `hasPendingRewards`: [2](#0-1) 

`_redistributeDebtAndColl` computes both accumulators independently — `BNBRewardPerUnitStaked` can round to zero while `USDSDebtRewardPerUnitStaked` does not: [3](#0-2) 

`_adjustTrove` calls `applyPendingRewards` then reads the stored (potentially stale) debt for the ICR check: [4](#0-3) 

`getPendingUSDSDebtReward` independently checks `L_USDSDebt` vs the snapshot and would return > 0 even when `hasPendingRewards` returns false: [5](#0-4) 

---

## Verdict
HIGH_CONFIDENCE_CANDIDATE

## Paid Scope Match
fund_extraction

## Exact Code Path
file: `src/TroveManager.sol`
function: `hasPendingRewards`, `_applyPendingRewards`, `_redistributeDebtAndColl`
symbols/lines:
- `hasPendingRewards` L1225–1236: returns `rewardSnapshots[_borrower].BNB < L_BNB` — no check on `L_USDSDebt`
- `_applyPendingRewards` L1150: entire body gated on `hasPendingRewards`
- `_redistributeDebtAndColl` L1329–1339: `BNBRewardPerUnitStaked` and `USDSDebtRewardPerUnitStaked` computed independently; `L_BNB` can stay unchanged while `L_USDSDebt` increases
- `src/BorrowerOperations.sol` L443–470: `applyPendingRewards` called (no-op), then `getTroveDebt` reads stale stored debt for ICR check

## Attacker Path
**preconditions:**
1. System has `totalStakes > _coll_liquidated * DECIMAL_PRECISION` (e.g., `totalStakes = 2e18`, `_coll = 1 wei`), so `BNBNumerator = 1e18 < totalStakes` → `BNBRewardPerUnitStaked = 0`.
2. The liquidated trove has non-trivial debt (minimum 2000 USDS = 2000e18), so `USDSDebtNumerator = 2000e18 * 1e18 >> totalStakes` → `USDSDebtRewardPerUnitStaked > 0`.
3. Survivor trove's `rewardSnapshots[survivor].BNB == L_BNB` (unchanged), `rewardSnapshots[survivor].USDSDebt < L_USDSDebt` (increased).

**attacker-controlled inputs:**
- Survivor trove owner calls `withdrawColl(_collWithdrawal, ...)` on `BorrowerOperations`.

**call sequence:**
1. Dust-collateral trove is liquidated → `_redistributeDebtAndColl(_debt, 1 wei)` → `L_BNB` unchanged, `L_USDSDebt` += `USDSDebtRewardPerUnitStaked`.
2. Survivor calls `BorrowerOperations.withdrawColl(X, ...)`.
3. `_adjustTrove` → `troveManager.applyPendingRewards(survivor)` → `hasPendingRewards` checks `rewardSnapshots[survivor].BNB < L_BNB` → **false** → no-op.
4. `vars.debt = getTroveDebt(survivor)` → returns stale stored debt (missing `pendingUSDSDebtReward`).
5. ICR check: `newICR = CR(coll - X, stale_debt, price)` — passes because debt is understated.
6. Collateral `X` is sent to attacker; debt is never incremented by the pending redistribution.

## Why Existing Checks Fail

`hasPendingRewards` is the sole gate for `_applyPendingRewards`. It only checks `rewardSnapshots[_borrower].BNB < L_BNB`. When `BNBRewardPerUnitStaked` rounds to zero (dust `_coll` with large `totalStakes`), `L_BNB` is not incremented, so the BNB snapshot equality holds and `hasPendingRewards` returns `false`. The USDS debt snapshot (`rewardSnapshots[_borrower].USDSDebt`) is never checked here. `getPendingUSDSDebtReward` would return a positive value (since `L_USDSDebt > rewardSnapshots[_borrower].USDSDebt`), but it is never applied to `Troves[_borrower].debt` because the entire `_applyPendingRewards` body is skipped. The subsequent `getTroveDebt` call in `_adjustTrove` reads the stale stored value, and the ICR check is performed against understated debt.

`_getCurrentTroveAmounts` (used by `getNominalICR`/`getCurrentICR`) does correctly add `getPendingUSDSDebtReward`, but `_adjustTrove` does not use those view functions for its ICR check — it reads `getTroveDebt` directly after the no-op `applyPendingRewards`.

## Rejection Checks
**expected behavior checked:** No — the design intent is that `hasPendingRewards` acts as a proxy for "any redistribution occurred since last snapshot." The assumption that `L_BNB` always increases when `L_USDSDebt` increases is broken by integer division rounding on dust collateral.

**prior report checked:** This is a known class of issue in Liquity forks, but the specific trigger (BNB-only gate in `hasPendingRewards` with independent rounding of the two accumulators) is a concrete code-level root cause distinct from generic "rounding" reports.

**README/NatSpec checked:** No documentation acknowledges this divergence.

**unsupported assumption checked:** No oracle failure, no admin action, no malicious token required. The dust liquidation can arise naturally from redemptions reducing a trove's collateral to near-zero, or from a trove opened at minimum collateral whose price drops.

## Local Proof Required
**test type:** Foundry unit test

**test file to add:** `test/TroveManager_DustRedistribution.t.sol`

**test setup:**
1. Deploy full protocol stack.
2. Open two troves: Trove A (survivor, large collateral e.g. 10 BNB, 10000 USDS), Trove B (dust, collateral = 1 wei, debt = minimum USDS — achieved by opening at valid ICR then redeeming down to 1 wei collateral, or by manipulating price to make it liquidatable).
3. Ensure `totalStakes > 1e18` (satisfied by Trove A alone if stake ≥ 2 BNB).
4. Liquidate Trove B.

**expected assertion:**
```solidity
assertEq(troveManager.L_BNB(), L_BNB_before);           // L_BNB unchanged
assertGt(troveManager.L_USDSDebt(), L_USDSDebt_before); // L_USDSDebt increased
assertFalse(troveManager.hasPendingRewards(survivorAddr));
assertGt(troveManager.getPendingUSDSDebtReward(survivorAddr), 0);
// Survivor withdraws collateral that should be blocked by correct debt
uint debtBefore = troveManager.getTroveDebt(survivorAddr);
borrowerOps.withdrawColl(excessAmount, ...); // should revert but does not
assertEq(troveManager.getTroveDebt(survivorAddr), debtBefore); // debt never updated
```

**failure condition:** If `hasPendingRewards` returned `true` (or also checked `USDSDebt` snapshot), `_applyPendingRewards` would apply the pending debt, `getTroveDebt` would return the correct higher value, and the collateral withdrawal would be blocked by the ICR check.

### Citations

**File:** src/TroveManager.sol (L1150-1179)
```text
        if (hasPendingRewards(_borrower)) {
            _requireTroveIsActive(_borrower);

            // Compute pending rewards
            uint pendingBNBReward = getPendingBNBReward(_borrower);
            uint pendingUSDSDebtReward = getPendingUSDSDebtReward(_borrower);

            // Apply pending rewards to trove's state
            Troves[_borrower].coll = Troves[_borrower].coll.add(pendingBNBReward);
            Troves[_borrower].debt = Troves[_borrower].debt.add(pendingUSDSDebtReward);

            _updateTroveRewardSnapshots(_borrower);

            // Transfer from DefaultPool to ActivePool
            _movePendingTroveRewardsToActivePool(
                _activePool,
                _defaultPool,
                pendingUSDSDebtReward,
                pendingBNBReward
            );

            emit TroveUpdated(
                _borrower,
                Troves[_borrower].debt,
                Troves[_borrower].coll,
                Troves[_borrower].stake,
                TroveManagerOperation.applyPendingRewards
            );
        }
    }
```

**File:** src/TroveManager.sol (L1210-1223)
```text
    function getPendingUSDSDebtReward(address _borrower) public view override returns (uint) {
        uint snapshotUSDSDebt = rewardSnapshots[_borrower].USDSDebt;
        uint rewardPerUnitStaked = L_USDSDebt.sub(snapshotUSDSDebt);

        if (rewardPerUnitStaked == 0 || Troves[_borrower].status != Status.active) {
            return 0;
        }

        uint stake = Troves[_borrower].stake;

        uint pendingUSDSDebtReward = stake.mul(rewardPerUnitStaked).div(DECIMAL_PRECISION);

        return pendingUSDSDebtReward;
    }
```

**File:** src/TroveManager.sol (L1225-1236)
```text
    function hasPendingRewards(address _borrower) public view override returns (bool) {
        /*
         * A Trove has pending rewards if its snapshot is less than the current rewards per-unit-staked sum:
         * this indicates that rewards have occured since the snapshot was made, and the user therefore has
         * pending rewards
         */
        if (Troves[_borrower].status != Status.active) {
            return false;
        }

        return (rewardSnapshots[_borrower].BNB < L_BNB);
    }
```

**File:** src/TroveManager.sol (L1325-1339)
```text
        uint BNBNumerator = _coll.mul(DECIMAL_PRECISION).add(lastBNBError_Redistribution);
        uint USDSDebtNumerator = _debt.mul(DECIMAL_PRECISION).add(lastUSDSDebtError_Redistribution);

        // Get the per-unit-staked terms
        uint BNBRewardPerUnitStaked = BNBNumerator.div(totalStakes);
        uint USDSDebtRewardPerUnitStaked = USDSDebtNumerator.div(totalStakes);

        lastBNBError_Redistribution = BNBNumerator.sub(BNBRewardPerUnitStaked.mul(totalStakes));
        lastUSDSDebtError_Redistribution = USDSDebtNumerator.sub(
            USDSDebtRewardPerUnitStaked.mul(totalStakes)
        );

        // Add per-unit-staked terms to the running totals
        L_BNB = L_BNB.add(BNBRewardPerUnitStaked);
        L_USDSDebt = L_USDSDebt.add(USDSDebtRewardPerUnitStaked);
```

**File:** src/BorrowerOperations.sol (L443-470)
```text
            contractsCache.troveManager.applyPendingRewards(_borrower);
        }

        {
            // Get the collChange based on whether or not BNB was sent in the transaction
            (vars.collChange, vars.isCollIncrease) = _getCollChange(collateral, adjustTroveParam.collWithdrawal);

            vars.netDebtChange = adjustTroveParam.USDSChange;

            TriggerBorrowingFeeParam memory triggerBorrowingFeeParam = TriggerBorrowingFeeParam({
                troveManager: contractsCache.troveManager,
                usdsToken: contractsCache.usdsToken,
                USDSAmount: adjustTroveParam.USDSChange,
                maxFeePercentage: adjustTroveParam.maxFeePercentage,
                oracleRate: oracleRate
            });

            // If the adjustment incorporates a debt increase and system is in Normal Mode, then trigger a borrowing fee
            if (adjustTroveParam.isDebtIncrease && !isRecoveryMode) {
                vars.USDSFee = _triggerBorrowingFee(triggerBorrowingFeeParam);
                vars.netDebtChange = vars.netDebtChange.add(vars.USDSFee); // The raw debt change includes the fee
            }

            vars.debt = contractsCache.troveManager.getTroveDebt(_borrower);
            vars.coll = contractsCache.troveManager.getTroveColl(_borrower);

            // Get the trove's old ICR before the adjustment, and what its new ICR will be after the adjustment
            vars.oldICR = LiquityMath._computeCR(vars.coll, vars.debt, vars.price);
```
