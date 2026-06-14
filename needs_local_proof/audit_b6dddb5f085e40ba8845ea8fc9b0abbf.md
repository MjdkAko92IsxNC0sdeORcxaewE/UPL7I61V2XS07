<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_3adefb93-3cd3-4b9b-8dd1-e188ca282fe6?mode=deep -->
<!-- deepwiki_verdict: needs_local_proof -->

## Verdict
NEEDS_LOCAL_PROOF

## Paid Scope Match
reward_extraction

## Exact Code Path

**file:** `src/OracleRateCalculation.sol`
**function:** `getOracleRate`
**symbols/lines:** lines 19–27

The confirmed reachable zero-rate path:

```
oracleKey == bytes32("PYTH")
deviationPyth == 0
publishTimePyth == block.timestamp  →  absDelayTime == 0
oracleRate = 0 + 0 = 0  (no floor applied here)
``` [1](#0-0) 

**file:** `src/SystemState.sol`
**function:** `getBorrowingFeeFloor` / storage `borrowingFeeFloor`
**symbols/lines:** lines 29, 92–94

The floor is a configurable runtime value, not a compile-time constant, stored in `SystemState`. [2](#0-1) [3](#0-2) 

**file:** `src/TroveManager.sol`
**function:** `getBorrowingFee` (implementation not fully read — this is the critical unverified link)
**symbols/lines:** lines 42 (MAX_BORROWING_FEE constant only confirmed) [4](#0-3) 

## Attacker Path

**preconditions:**
- Pyth oracle key is `bytes32("PYTH")`
- A fresh Pyth price update is submitted with `deviationPyth = 0` and `publishTimePyth == block.timestamp` (both are normal, non-manipulated values)
- `baseRate` in `TroveManager` has decayed toward zero (time has passed since last fee operation)
- `getBorrowingFee` does NOT apply `max(calculatedFee, borrowingFeeFloor)` — **this is the unverified assumption**

**attacker-controlled inputs:**
- Calls `openTrove` with any valid `USDSAmount` and sufficient collateral
- The oracle state (`deviationPyth=0`, fresh `publishTimePyth`) is a normal market condition, not attacker-controlled

**call sequence:**
1. `OracleRateCalculation.getOracleRate(bytes32("PYTH"), 0, block.timestamp)` → returns `0`
2. `BorrowerOperations.openTrove(...)` → calls `TroveManager.getBorrowingFee(USDSAmount, 0)`
3. If fee = `USDSAmount * (baseRate + 0)` with no floor enforcement → fee < `borrowingFeeFloor * USDSAmount / 1e18`
4. Borrower receives USDS paying sub-floor fee; `SableStakingV2` receives less USDS than the protocol's guaranteed minimum per unit issued

## Why Existing Checks Fail

`OracleRateCalculation.getOracleRate` applies a ceiling (`MAX_ORACLE_RATE_PERCENTAGE = 0.25%`) but **no floor** — it can return exactly `0`. [5](#0-4) 

`SystemState` stores `borrowingFeeFloor` and exposes `getBorrowingFeeFloor()`, but whether `TroveManager.getBorrowingFee` calls `max(fee, floor)` or simply returns `USDSAmount * rate` could not be confirmed from the available reads. In the original Liquity codebase the floor is enforced inside `getBorrowingFee`; if Sable's fork omits or misplaces that `max()` call, the floor is bypassed whenever `oracleRate + baseRate < borrowingFeeFloor`.

## Rejection Checks

**expected behavior checked:** `oracleRate = 0` is a normal, non-adversarial market condition (fresh price, zero deviation). It is not an oracle failure or manipulation. The question is whether the protocol's own floor enforcement is present.

**prior report checked:** No evidence of a prior report on this specific path in the indexed codebase.

**README/NatSpec checked:** No NatSpec or README text found that documents `oracleRate=0` as an accepted edge case with no floor guarantee.

**unsupported assumption checked:** The only assumption is that `getBorrowingFee` lacks a `max(fee, floor)` guard — this is the single unverified link that requires local code reading and a test.

## Local Proof Required

**test type:** Foundry unit test

**test file to add:** `test/BorrowerOperations_OracleRateZero.t.sol`

**test setup:**
1. Deploy `OracleRateCalculation` and confirm `getOracleRate(bytes32("PYTH"), 0, block.timestamp) == 0`
2. Wire full protocol (or use existing test harness) with this oracle
3. Let `baseRate` decay to near zero (warp time)
4. Call `openTrove` with a known `USDSAmount`
5. Capture the `USDSBorrowingFeePaid` event or read the fee minted to `SableStakingV2`

**expected assertion:**
```solidity
uint floor = systemState.getBorrowingFeeFloor();
assertGe(
    USDSBorrowingFeePaid,
    USDSAmount * floor / 1e18,
    "fee below floor: stakers receive less than guaranteed minimum"
);
```

**failure condition:** If the assertion fails (fee < floor), the bug is confirmed: borrowers can open troves paying sub-floor fees whenever Pyth reports a fresh zero-deviation price, and SABLE stakers receive less USDS reward than the protocol invariant guarantees per unit of USDS issued.

### Citations

**File:** src/OracleRateCalculation.sol (L12-31)
```text
    uint constant public MAX_ORACLE_RATE_PERCENTAGE = 25 * DECIMAL_PRECISION / 10000; // 0.25% * DECIMAL_PRECISION

    function getOracleRate(
        bytes32 oracleKey, 
        uint deviationPyth, 
        uint publishTimePyth
    ) external view override returns (uint oracleRate) {
        if (oracleKey == bytes32("PYTH")) {
            uint absDelayTime = block.timestamp > publishTimePyth 
                ? block.timestamp.sub(publishTimePyth)
                : publishTimePyth.sub(block.timestamp);
            
            oracleRate = deviationPyth.add(absDelayTime.mul(DECIMAL_PRECISION).div(10000));
            if (oracleRate > MAX_ORACLE_RATE_PERCENTAGE) {
                oracleRate = MAX_ORACLE_RATE_PERCENTAGE;
            }
        } else {
            oracleRate = MAX_ORACLE_RATE_PERCENTAGE;
        }
    }
```

**File:** src/SystemState.sol (L29-29)
```text
    uint private borrowingFeeFloor; // 0.05%
```

**File:** src/SystemState.sol (L92-94)
```text
    function getBorrowingFeeFloor() external view override returns (uint) {
        return borrowingFeeFloor;
    }
```

**File:** src/TroveManager.sol (L42-42)
```text
    uint public constant MAX_BORROWING_FEE = (DECIMAL_PRECISION / 100) * 5; // 5%
```
