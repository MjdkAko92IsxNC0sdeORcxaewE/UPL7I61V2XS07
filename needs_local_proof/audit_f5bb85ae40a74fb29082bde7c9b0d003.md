<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_7d823525-0181-446d-9f2f-552d0ca85106?mode=deep -->
<!-- deepwiki_verdict: needs_local_proof -->

## Verdict
NEEDS_LOCAL_PROOF

## Paid Scope Match
reward_extraction

## Exact Code Path

**file:** `src/SABLE/SableStakingV2.sol`

**function:** `increaseF_SABLE`, `_getPendingSABLEGain`, `stake`, `unstake`

**symbols/lines:**

The accumulator update at the core of the vulnerability: [1](#0-0) 

The gain computation that mirrors it: [2](#0-1) 

`issueSABLE()` called unconditionally at the top of both entry points: [3](#0-2) [4](#0-3) 

`unstake(0)` path — gains are sent regardless of `_sableLPAmount`: [5](#0-4) 

## Attacker Path

**preconditions:**
- Attacker holds a large quantity of SableLP tokens (e.g., `L` wei).
- No other stakers exist, or attacker is the dominant staker such that after step 3 `totalSableLPStaked = 1`.
- `SableRewarder` (deployed, address set as `sableRewarderAddress`) calls `increaseF_SABLE(issuance)` inside its `issueSABLE()` — this is the one unverified link (see below).

**attacker-controlled inputs:**
- `stake(L)` — initial large stake
- `unstake(L - 1)` — reduces own stake to 1 wei
- `stake(L)` — re-stakes, triggering `issueSABLE()` while `totalSableLPStaked == 1`
- `unstake(0)` — optional harvest of any residual gain

**call sequence:**

1. `sableLPToken.approve(stakingContract, L)`; `stake(L)` → attacker's stake = `L`, `totalSableLPStaked = L`.
2. Wait `T1` seconds. Rewards `R1` accumulate; `F_SABLE` increases by `R1 * 1e18 / L`.
3. `unstake(L - 1)` → `issueSABLE()` fires, `F_SABLE` updated; attacker collects `R1` proportionally; snapshot reset; `stakes[attacker] = 1`, `totalSableLPStaked = 1`.
4. Wait `T2` seconds. Rewards `R2` accumulate in the rewarder but `issueSABLE()` has not been called yet, so `F_SABLE` is not yet updated.
5. `stake(L)` → `issueSABLE()` fires → `increaseF_SABLE(R2)` → `SABLEGainPerSABLEStaked = R2 * 1e18 / 1 = R2 * 1e18`; `F_SABLE += R2 * 1e18`. Then `currentStake = 1 ≠ 0`, so `SABLEGain = 1 * R2 * 1e18 / 1e18 = R2`. Attacker receives `R2` SABLE — 100% of the period's issuance — despite holding only 1 wei of stake.
6. `unstake(0)` — collects any residual gain from the re-stake period.

## Why Existing Checks Fail

**`increaseF_SABLE` has no floor on `totalSableLPStaked`:** [1](#0-0) 
The guard `if (totalSableLPStaked > 0)` only prevents division-by-zero; it does not prevent the degenerate case where `totalSableLPStaked = 1` causes `SABLEGainPerSABLEStaked = issuance * 1e18`, making the per-unit accumulator jump by the entire issuance amount.

**`_getPendingSABLEGain` is purely linear in stake:** [2](#0-1) 
`1 * (R2 * 1e18) / 1e18 = R2` — the 1-wei stake earns the full issuance with no rounding loss.

**`unstake` sends gains unconditionally even for `_sableLPAmount = 0`:** [6](#0-5) 
There is no minimum-stake-to-claim guard.

**`stake` sends gains whenever `currentStake != 0`:** [7](#0-6) 
A 1-wei `currentStake` qualifies.

## Rejection Checks

**expected behavior checked:** No — the invariant "reward entitlement proportional to stake fraction" is explicitly broken. A 1-wei stake claiming 100% of issuance is not expected behavior.

**prior report checked:** The 1-wei accumulator attack is a known class of vulnerability in Liquity-style reward accumulators, but its applicability here depends on whether `SableRewarder.issueSABLE()` calls `increaseF_SABLE()` — that implementation file is absent from this repo.

**README/NatSpec checked:** No documentation acknowledges or accepts this behavior.

**unsupported assumption checked:** The one assumption that cannot be verified from source alone is that `SableRewarder.issueSABLE()` calls `sableStaking.increaseF_SABLE(issuance)`. The interface confirms `issueSABLE()` exists: [8](#0-7) 
But `SableRewarder.sol` has no implementation file in this repository — only the interface is present. The call chain `issueSABLE() → increaseF_SABLE()` is architecturally required (otherwise `F_SABLE` could never be updated), but it must be confirmed in the deployed bytecode or a local test.

## Local Proof Required

**test type:** Foundry integration test

**test file to add:** `test/SableStakingRewardManipulation.t.sol`

**test setup:**
- Deploy mock `SableLPToken`, `SABLEToken`, `USDSToken`.
- Deploy `SableStakingV2` and a concrete `SableRewarder` (obtain from deployment artifacts or bytecode).
- Wire addresses; fund rewarder with SABLE.
- Mint `L = 1e24` LP tokens to attacker; approve staking contract.

**expected assertion:**
```
// After the 6-step sequence:
uint attackerSABLE = sableToken.balanceOf(attacker);
uint R2 = /* issuance during T2 */;
// Attacker should only be entitled to ~0 (1/L fraction of R2)
// but receives R2 (100%)
assertApproxEqAbs(attackerSABLE_from_period2, R2, 1e9);
// Proportional entitlement:
uint entitled = R2 * 1 / (1 + L); // ≈ 0
assertGt(attackerSABLE_from_period2, entitled * 1000); // >1000x overpayment
```

**failure condition:** If `SableRewarder.issueSABLE()` does NOT call `increaseF_SABLE()`, `F_SABLE` never updates and the attack collapses — verdict would revert to REJECT. If it does call `increaseF_SABLE()`, the math above is deterministic and the test will pass, confirming a HIGH_CONFIDENCE reward extraction bug.

### Citations

**File:** src/SABLE/SableStakingV2.sol (L127-127)
```text
        sableRewarder.issueSABLE();
```

**File:** src/SABLE/SableStakingV2.sol (L135-161)
```text
        if (currentStake != 0) {
            BNBGain = _getPendingBNBGain(msg.sender);
            USDSGain = _getPendingUSDSGain(msg.sender);
            SABLEGain = _getPendingSABLEGain(msg.sender);
        }
    
        _updateUserSnapshots(msg.sender);

        uint newStake = currentStake.add(_sableLPAmount);

        // Increase user’s stake and total SABLE staked
        stakes[msg.sender] = newStake;
        totalSableLPStaked = totalSableLPStaked.add(_sableLPAmount);
        emit TotalSableLPStakedUpdated(totalSableLPStaked);

        // Transfer SABLE from caller to this contract
        sableLPToken.transferFrom(msg.sender, address(this), _sableLPAmount);

        emit StakeChanged(msg.sender, newStake);
        emit StakingGainsWithdrawn(msg.sender, USDSGain, BNBGain, SABLEGain);

         // Send accumulated BNB, USDS and SABLE to the caller
        if (currentStake != 0) {
            usdsToken.transfer(msg.sender, USDSGain);
            sableToken.transfer(msg.sender, SABLEGain);
            _sendBNBGainToUser(BNBGain);
        }
```

**File:** src/SABLE/SableStakingV2.sol (L169-169)
```text
        sableRewarder.issueSABLE();
```

**File:** src/SABLE/SableStakingV2.sol (L181-202)
```text
        if (_sableLPAmount > 0) {
            uint SableLPToWithdraw = LiquityMath._min(_sableLPAmount, currentStake);

            uint newStake = currentStake.sub(SableLPToWithdraw);

            // Decrease user's stake and total SABLE staked
            stakes[msg.sender] = newStake;
            totalSableLPStaked = totalSableLPStaked.sub(SableLPToWithdraw);
            emit TotalSableLPStakedUpdated(totalSableLPStaked);

            // Transfer unstaked SABLE to user
            sableLPToken.transfer(msg.sender, SableLPToWithdraw);

            emit StakeChanged(msg.sender, newStake);
        }

        emit StakingGainsWithdrawn(msg.sender, USDSGain, BNBGain, SABLEGain);

        // Send accumulated USDS, BNB and SABLE gains to the caller
        usdsToken.transfer(msg.sender, USDSGain);
        sableToken.transfer(msg.sender, SABLEGain);
        _sendBNBGainToUser(BNBGain);
```

**File:** src/SABLE/SableStakingV2.sol (L229-234)
```text
        uint SABLEGainPerSABLEStaked;
        
        if (totalSableLPStaked > 0) {SABLEGainPerSABLEStaked = _SABLEGain.mul(DECIMAL_PRECISION).div(totalSableLPStaked);}
        
        F_SABLE = F_SABLE.add(SABLEGainPerSABLEStaked);
        emit F_SABLEUpdated(F_SABLE);
```

**File:** src/SABLE/SableStakingV2.sol (L263-266)
```text
    function _getPendingSABLEGain(address _user) internal view returns (uint) {
        uint F_SABLE_Snapshot = snapshots[_user].F_SABLE_Snapshot;
        uint SABLEGain = stakes[_user].mul(F_SABLE.sub(F_SABLE_Snapshot)).div(DECIMAL_PRECISION);
        return SABLEGain;
```

**File:** src/Interfaces/ISableRewarder.sol (L22-22)
```text
    function issueSABLE() external;
```
