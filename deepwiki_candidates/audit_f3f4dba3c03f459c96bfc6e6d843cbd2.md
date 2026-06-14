<!-- deepwiki_source_url: https://deepwiki.com/search/-deepwiki-candidate-triage-pro_e9836e19-6b07-4358-a2c1-bc0e9ccaccf9?mode=deep -->
<!-- deepwiki_verdict: high_confidence_candidate -->

## Verdict
HIGH_CONFIDENCE_CANDIDATE

## Paid Scope Match
reward_extraction

## Exact Code Path

**file:** `src/SABLE/CommunityIssuance.sol`
**function:** `issueSABLE()`
**symbols/lines:** lines 72–79 — uncapped linear issuance with no `min(issuance, sableToken.balanceOf(address(this)))` guard [1](#0-0) 

**file:** `src/StabilityPool.sol`
**function:** `_updateG()`, `_payOutSABLEGains()`
**symbols/lines:** lines 494–513 (G inflation from uncapped issuance), lines 996–1011 (unconditional `sendSABLE` transfer) [2](#0-1) [3](#0-2) 

## Attacker Path

**preconditions:**
- `latestRewardPerSec = 5e15` (live value)
- CommunityIssuance SABLE balance ≈ 5409 SABLE (live value)
- Balance exhaustion time from `lastIssuanceTime = 1727614847` (Oct 2024): `5409e18 / 5e15 ≈ 1,081,983 seconds ≈ 12.5 days` — already elapsed as of June 2026
- Two or more depositors have existing deposits in StabilityPool (live `totalUSDSDeposits ≈ 6579 USDS`)

**attacker-controlled inputs:**
- None required beyond being a normal StabilityPool depositor; timing is the only variable

**call sequence:**
1. Depositor A calls `withdrawFromSP(amount, ...)` or `provideToSP(amount, ...)`
2. → `_triggerSABLEIssuance(communityIssuance)`
3. → `communityIssuance.issueSABLE()` returns `issuance = 5e15 * elapsed` (e.g., ~2.8e23 for ~56M seconds elapsed), far exceeding the ~5.4e21 actual balance
4. → `_updateG(2.8e23)` inflates `epochToScaleToG` by a factor of ~52× over actual balance
5. → `_payOutSABLEGains(...)` → `communityIssuance.sendSABLE(depositorA, inflatedGain)` — succeeds, draining the contract
6. Depositor B calls `withdrawFromSP(...)` → same path → `sendSABLE(depositorB, inflatedGain)` → `sableToken.transfer()` **reverts** (ERC20 insufficient balance) [4](#0-3) 

## Why Existing Checks Fail

**`issueSABLE()` has no balance cap.** The only arithmetic is `latestRewardPerSec.mul(timeSinceLastIssue)` with no `min(..., sableToken.balanceOf(address(this)))`. `totalSABLEIssued` is a monotonically increasing counter with no ceiling enforcement. [5](#0-4) 

**`_updateG()` only guards against `totalUSDS == 0 || _SABLEIssuance == 0`.** There is no check that `_SABLEIssuance <= sableToken.balanceOf(communityIssuance)`. The G accumulator is inflated unconditionally when both conditions are false. [6](#0-5) 

**`sendSABLE()` has no balance guard.** It calls `sableToken.transfer(_account, _SABLEamount)` directly; the ERC20 transfer reverts on insufficient balance, which means the second claimant's entire `withdrawFromSP` or `provideToSP` transaction reverts — they cannot recover their USDS deposit or BNB gain either until the contract is refunded. [4](#0-3) 

**Live data confirms the scenario is already triggered:** `lastIssuanceTime = 1727614847` (Oct 2024), `latestRewardPerSec = 5e15`, balance ≈ 5409 SABLE. Balance exhaustion occurred ~12.5 days after Oct 2024. As of June 2026, any call to `issueSABLE()` would return an issuance value ~52× the actual balance. [7](#0-6) 

## Rejection Checks

**expected behavior checked:** No — Liquity's original design used a decaying exponential bounded by total supply. Sable replaced it with a linear rate model but omitted the corresponding balance cap. This is a design regression, not intended behavior.

**prior report checked:** Not flagged in `live-context/` files or any known-issue list in the repository.

**README/NatSpec checked:** The `_updateG()` comment only documents the `totalUSDS == 0` skip case; no mention of balance exhaustion handling. [8](#0-7) 

**unsupported assumption checked:** No oracle manipulation, no admin key, no malicious token — only normal time passage and a normal depositor interaction.

## Local Proof Required

**test type:** Foundry fuzz/integration test

**test file to add:** `test/CommunityIssuanceOverIssuance.t.sol`

**test setup:**
1. Deploy full protocol stack (or fork BSC mainnet at a recent block)
2. Ensure two depositors (Alice, Bob) each have equal USDS deposits in StabilityPool
3. Set `latestRewardPerSec` such that `latestRewardPerSec * T > sableToken.balanceOf(communityIssuance)` for some elapsed time `T`
4. `vm.warp(block.timestamp + T + 1)`

**call sequence:**
```
alice.withdrawFromSP(0, ...)  // triggers issueSABLE, inflates G, pays Alice
bob.withdrawFromSP(0, ...)    // should revert at sendSABLE
```

**expected assertion:**
- Alice's received SABLE > `initialBalance / 2` (overclaim beyond proportional share)
- Bob's `withdrawFromSP` reverts with ERC20 transfer failure
- `sableToken.balanceOf(communityIssuance) == 0` after Alice's claim

**failure condition:** If `issueSABLE()` caps its return value at `sableToken.balanceOf(address(this))`, both assertions fail and the finding is invalid.

### Citations

**File:** src/SABLE/CommunityIssuance.sol (L69-80)
```text
    function issueSABLE() external override returns (uint) {
        _requireCallerIsStabilityPool();

        uint timeSinceLastIssue = block.timestamp.sub(lastIssuanceTime);
        uint issuance = latestRewardPerSec.mul(timeSinceLastIssue);
        
        totalSABLEIssued = totalSABLEIssued.add(issuance);
        lastIssuanceTime = block.timestamp;

        emit TotalSABLEIssuedUpdated(totalSABLEIssued);
        return issuance;
    }
```

**File:** src/SABLE/CommunityIssuance.sol (L89-93)
```text
    function sendSABLE(address _account, uint _SABLEamount) external override {
        _requireCallerIsStabilityPool();

        sableToken.transfer(_account, _SABLEamount);
    }
```

**File:** src/StabilityPool.sol (L494-513)
```text
    function _updateG(uint _SABLEIssuance) internal {
        uint totalUSDS = totalUSDSDeposits; // cached to save an SLOAD
        /*
         * When total deposits is 0, G is not updated. In this case, the SABLE issued can not be obtained by later
         * depositors - it is missed out on, and remains in the balanceof the CommunityIssuance contract.
         *
         */
        if (totalUSDS == 0 || _SABLEIssuance == 0) {
            return;
        }

        uint SABLEPerUnitStaked;
        SABLEPerUnitStaked = _computeSABLEPerUnitStaked(_SABLEIssuance, totalUSDS);

        uint marginalSABLEGain = SABLEPerUnitStaked.mul(P);
        epochToScaleToG[currentEpoch][currentScale] = epochToScaleToG[currentEpoch][currentScale]
            .add(marginalSABLEGain);

        emit G_Updated(epochToScaleToG[currentEpoch][currentScale], currentEpoch, currentScale);
    }
```

**File:** src/StabilityPool.sol (L996-1011)
```text
    function _payOutSABLEGains(
        ICommunityIssuance _communityIssuance,
        address _depositor,
        address _frontEnd
    ) internal {
        // Pay out front end's SABLE gain
        if (_frontEnd != address(0)) {
            uint frontEndSABLEGain = getFrontEndSABLEGain(_frontEnd);
            _communityIssuance.sendSABLE(_frontEnd, frontEndSABLEGain);
            emit SABLEPaidToFrontEnd(_frontEnd, frontEndSABLEGain);
        }

        // Pay out depositor's SABLE gain
        uint depositorSABLEGain = getDepositorSABLEGain(_depositor);
        _communityIssuance.sendSABLE(_depositor, depositorSABLEGain);
        emit SABLEPaidToDepositor(_depositor, depositorSABLEGain);
```

**File:** aarc-audit/live-context/state-model.md (L143-146)
```markdown
- CommunityIssuance SABLE balance: `5409915403529186761416`.
- `totalSABLEIssued`: `827119683802499810000000`.
- `lastIssuanceTime`: `1727614847`.
- `latestRewardPerSec`: `5000000000000000`.
```
