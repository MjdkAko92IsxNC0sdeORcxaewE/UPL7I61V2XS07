<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_06fd131d-c9c2-4c4c-b19c-c7483d0bdefe?mode=deep -->
<!-- deepwiki_verdict: needs_local_proof -->

## Verdict
NEEDS_LOCAL_PROOF

## Paid Scope Match
fund_extraction

## Exact Code Path

**file:** `src/BorrowerOperations.sol`
**function:** `openTrove`
**symbols/lines:** Lines 269–278 — reads `systemState.getUSDSGasCompensation()` at open time and mints exactly that amount to GasPool. [1](#0-0) 

**file:** `src/TroveManager.sol`
**function:** `_liquidateRecoveryMode`
**symbols/lines:** Line 234 — reads the *current* `systemState.getUSDSGasCompensation()` at liquidation time, not the amount deposited at open time. [2](#0-1) 

**file:** `src/TroveHelper.sol`
**function:** `getCappedOffsetVals`
**symbols/lines:** Line 48 — also reads the *current* `systemState.getUSDSGasCompensation()` for the capped-offset branch. [3](#0-2) 

**file:** `src/TroveManager.sol`
**function:** `_sendGasCompensation`
**symbols/lines:** Lines 836–837 — calls `usdsToken.returnFromPool(gasPoolAddress, liquidator, totalUSDSGasCompensation)` with the new (higher) value. [4](#0-3) 

**file:** `src/USDSToken.sol`
**function:** `returnFromPool` / `_transfer`
**symbols/lines:** Lines 114–117 and 213–219 — `returnFromPool` is a plain ERC20 `_transfer` with SafeMath `sub`; it reverts if GasPool balance is insufficient. [5](#0-4) [6](#0-5) 

**file:** `src/SystemState.sol`
**function:** `setUSDSGasCompensation`
**symbols/lines:** Lines 64–66 — timelock-only setter that changes the global parameter with no per-trove reconciliation. [7](#0-6) 

---

## Attacker Path

**preconditions:**
- Two or more troves are open while `USDSGasCompensation = 10e18`; each trove's `compositeDebt` includes 10e18 and GasPool holds `N × 10e18` total.
- Timelock raises `USDSGasCompensation` to 20e18 (privileged but legitimate governance action).
- System enters recovery mode (TCR < CCR); at least one trove has MCR ≤ ICR < TCR.

**attacker-controlled inputs:**
- Unprivileged liquidator calls `liquidate(borrower)` or `liquidateTroves(n)` after the parameter change.

**call sequence:**
1. `openTrove` × N (while `USDSGasCompensation = 10e18`) → GasPool receives `N × 10e18`.
2. Timelock calls `SystemState.setUSDSGasCompensation(20e18)`.
3. Price drops; system enters recovery mode; target trove has MCR ≤ ICR < TCR.
4. Liquidator calls `TroveManager.liquidate(target)`.
5. `_liquidateRecoveryMode` → ICR ≥ MCR branch → `troveHelper.getCappedOffsetVals(...)` → `singleLiquidation.USDSGasCompensation = 20e18`.
6. `_addLiquidationValuesToTotals` accumulates `totalUSDSGasCompensation = 20e18`.
7. `_sendGasCompensation` calls `usdsToken.returnFromPool(gasPoolAddress, liquidator, 20e18)`.
8. GasPool has `N × 10e18`; if N ≥ 2 the transfer succeeds — liquidator receives 20e18 but only 10e18 was deposited for this trove. The remaining troves' gas compensation is silently consumed.

**Critical single-trove boundary:** If N = 1 (current live state: GasPool = 10e18), `returnFromPool` reverts via SafeMath underflow — the liquidation is blocked entirely (DoS, not extraction). Fund extraction only materialises when N ≥ 2. [8](#0-7) 

---

## Why Existing Checks Fail

There is no per-trove record of how much gas compensation was deposited. `openTrove` mints `systemState.getUSDSGasCompensation()` at open time into the shared GasPool, but the trove struct stores only `debt` (composite, including the gas comp amount at open time) — it does not store the exact gas comp amount separately. [1](#0-0) 

At liquidation time, both `_liquidateRecoveryMode` and `getCappedOffsetVals` re-read the *current* global `USDSGasCompensation` from `SystemState`, not the per-trove deposited amount. [2](#0-1) [3](#0-2) 

`setUSDSGasCompensation` has no guard that reconciles existing GasPool balances or prevents the mismatch. [7](#0-6) 

`_sendGasCompensation` performs no balance check before calling `returnFromPool`; it relies entirely on the ERC20 transfer reverting if GasPool is underfunded. [9](#0-8) 

---

## Rejection Checks

**expected behavior checked:** The GasPool comment and Liquity design assume a fixed gas compensation amount per trove. The protocol adds a timelock-mutable parameter without any migration or per-trove snapshot, which is not documented as intentional. [10](#0-9) 

**prior report checked:** No prior report found in the repository artifacts for this specific parameter-change/GasPool mismatch path.

**README/NatSpec checked:** No NatSpec on `setUSDSGasCompensation` acknowledges the GasPool underfunding risk. [11](#0-10) 

**unsupported assumption checked:** The timelock is a legitimate, deployed, non-malicious governance mechanism — not a leaked-key or malicious-admin assumption. The live context confirms the timelock address is `0x638675b7C2e056917567571307C6f6A7D69A258A`. [12](#0-11) 

---

## Local Proof Required

**test type:** Foundry fork or unit test

**test file to add:** `test/GasCompMismatch.t.sol`

**test setup:**
1. Deploy full protocol with `USDSGasCompensation = 10e18`.
2. Open two troves (Alice and Bob) — GasPool receives 20e18 total.
3. Impersonate timelock; call `SystemState.setUSDSGasCompensation(20e18)`.
4. Drop price so system enters recovery mode; set Alice's trove ICR between MCR and TCR.
5. Ensure StabilityPool has enough USDS to cover Alice's full debt.
6. Call `TroveManager.liquidate(alice)` as an unprivileged liquidator.

**expected assertion:**
- Liquidator USDS balance increases by 20e18 (not 10e18).
- GasPool USDS balance drops from 20e18 to 0 (Bob's gas comp consumed).
- Bob's subsequent `closeTrove` or liquidation reverts because GasPool is empty.

**failure condition:** If the test shows the liquidation reverts (SafeMath underflow in `returnFromPool`) even with two troves, the fund-extraction path does not hold and the impact degrades to DoS-only (rejectable). If it succeeds and liquidator receives 20e18, the extraction is confirmed.

### Citations

**File:** src/BorrowerOperations.sol (L268-278)
```text
            // Move the USDS gas compensation to the Gas Pool
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

**File:** src/TroveManager.sol (L234-234)
```text
        singleLiquidation.USDSGasCompensation = systemState.getUSDSGasCompensation();
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

**File:** src/TroveHelper.sol (L48-48)
```text
        singleLiquidation.USDSGasCompensation = systemState.getUSDSGasCompensation();
```

**File:** src/USDSToken.sol (L114-117)
```text
    function returnFromPool(address _poolAddress, address _receiver, uint256 _amount) external override {
        _requireCallerIsTroveMorSP();
        _transfer(_poolAddress, _receiver, _amount);
    }
```

**File:** src/USDSToken.sol (L213-219)
```text
    function _transfer(address sender, address recipient, uint256 amount) internal {
        assert(sender != address(0));
        assert(recipient != address(0));

        _balances[sender] = _balances[sender].sub(amount, "ERC20: transfer amount exceeds balance");
        _balances[recipient] = _balances[recipient].add(amount);
        emit Transfer(sender, recipient, amount);
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

**File:** aarc-audit/live-context/balances.md (L47-47)
```markdown
| USDS | GasPool | `10000000000000000000` |
```

**File:** src/GasPool.sol (L6-15)
```text
/**
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

**File:** aarc-audit/live-context/live-context.md (L134-134)
```markdown
- Core pool owners are zero. SystemState timelock is decoded as `0x638675b7C2e056917567571307C6f6A7D69A258A`; any risk-parameter mutation review should start there.
```
