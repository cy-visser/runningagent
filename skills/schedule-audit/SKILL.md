---
name: schedule-audit
description: Audits the runner's training schedule to calculate weekly volume, planned TSS, workout intensity distribution (easy vs tempo/intervals), travel alignment, and taper/recovery compliance.
---

# Schedule Audit & Assessment Skill

You are now equipped with the Schedule Audit & Assessment skill. Use this skill when the runner asks you to audit, assess, analyze, review, or check their training schedule or plan (e.g., "Assess my schedule until my race" or "Audit my running schedule for this month").

## Audit Protocol:

1. **Retrieve Data**:
   - Immediately call the `fetch_runner_status` tool for the requested date range. This will return a consolidated summary of planned workouts, calendar notes, and metrics.

2. **Rigorously Analyze the Schedule Week-by-Week**:
   - Perform a precise, manual calculation of:
     - **Total weekly mileage (km)**.
     - **Total planned TSS**.
     - **Workout intensity distribution**: Count the number of easy runs vs. hard/workout runs (e.g. tempo, threshold, or intervals) for each week.
   - Do not estimate or assume the plan is correct. Count the workouts and sum the distance/TSS exactly.

3. **Cross-Reference Calendar & Travel Notes**:
   - For each week in the audit range, check the retrieved calendar notes for travel plans (trips, vacations, cruises), business trips, or other context notes.
   - You MUST explicitly print any travel details (destination and dates) next to or under the corresponding weekly volume.
   - Provide tailored advice for managing running volume and workouts during travel, taking into account local climate (heat/humidity), timezone shifts, and facilities (like treadmill availability).

4. **Evaluate Workout Intensity & Balance**:
   - Check the composition of runs scheduled in each week. A standard week should contain no more than 1 to 2 hard workouts (tempo, threshold, or intervals).
   - If you detect 3 or more high-intensity runs in a single week, explicitly warn the runner that this is a severe injury and overtraining risk. Suggest specific adjustments (e.g., converting one of the hard workouts to an easy recovery jog).

5. **Evaluate Taper Compliance**:
   - For the week leading up to a major race (taper week), check the total running volume. It should be 40-60% lower than their peak weekly mileage.
   - If you detect high volume (e.g., >50km for a 30k/marathon taper) or long runs scheduled close to the race, explicitly warn the runner and suggest specific reductions.

6. **Evaluate Recovery Compliance**:
   - For the week following a major race (recovery week), review workouts for volume and intensity.
   - High-intensity workouts (TSS > 100) or long runs (>15km) scheduled in the first 7 days post-race are severe injury risks. You must explicitly call these out, explain the physiological risk of muscle damage, and instruct the runner to remove or replace them with active recovery walks/short easy jogs.

7. **Present the Audit**:
   - Deliver the audit clearly in your response.
   - For each week, use the following header format:
     `* **[Date Range]:** [Total Volume] km ([Total Runs] runs: [X] easy, [Y] tempo/interval) | TSS: [Total TSS] [Optional: (Travel to [Location] from [Start] to [End])]`
   - List the strengths of the plan first, then present the critical warnings and specific recommended adjustments.
