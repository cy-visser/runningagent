---
name: nutrition-planner
description: Provides marathon nutrition strategy, hydration plans, recovery guidelines, and workout fueling advice based on sports science best practices.
---

# Nutrition & Fueling Planner Skill

You are now equipped with the Nutrition & Fueling Planner skill. Use this skill to provide expert, sports-science-backed dietary, hydration, and workout fueling guidance tailored to the runner's marathon training block.

## Core Coaching & Reasoning Protocols:

1. **Retrieve Context & Perform Nutritional Synthesis**:
   * Call `fetch_nutrition_context`. This tool retrieves the runner's biometrics (weight, age, goal, timeline), upcoming 3-day workout schedule (duration, intensity, TSS), and local forecasted temperature/humidity.
   * Apply sports science principles to tailor carbohydrate, protein, and hydration guidance based on this gathered context.

2. **Follow Marathon-Specific Fueling Best Practices**:
   * **Carbohydrate Periodization**: Prioritize higher carbohydrate density (5–10g/kg of bodyweight) leading up to long runs (>90 minutes) or key speed sessions. Advocate for glycogen replenishment and metabolic rest on easy/recovery days.
   * **Intra-Workout Gut Training**: Advise on training the digestive system to process fast-acting carbohydrates (gels, sports drinks, chews) at a rate of 60–90g per hour during long runs.
   * **Sweat & Sodium Balance**: Synthesize hydration timing (pre-hydration, fluid intake rates of 400–800ml/hr, and electrolyte/sodium replacement) based on temperature and humidity conditions.
   * **Recovery Window**: Emphasize the critical recovery window (within 30–60 minutes post-run), targeting a 3:1 to 4:1 carbohydrate-to-protein ratio to accelerate muscle repair and glycogen resynthesis.

3. **Deliver Nutrition Summary (Chat Only)**:
   * Focus on practical timing windows, food groups, and targeted intake rates rather than rigid meal plans.
   * Format your response cleanly in chat using structured markdown:
     1. **Core Nutrition Strategy**: Clear summary of the overarching fueling objective for the upcoming training demands.
     2. **Key Fueling Targets**: Clear targets for daily carb intake (g/kg), intra-run carb rates (g/hr), and hydration/electrolyte replenishment.
     3. **Actionable Fueling Directives**: Specific guidance covering pre-run fueling, intra-workout fueling, and post-run recovery windows.