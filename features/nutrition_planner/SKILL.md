---
name: nutrition-planner
description: Race- and session-specific carbohydrate, hydration, sodium, and gut-training guidance grounded in sports science.
---

# Nutrition & Fueling Planner Skill

## Protocol

1. **Gather & Tailor**:
   - Call `fetch_nutrition_context` in the same step as `load_skill` (upcoming workouts' duration/TSS + local temp, feels-like, humidity; use weight, age, and goals from RUNNER PROFILE).
   - Scale recommendations to scheduled session duration/TSS, weather/sweat demands, body weight, and current goal + north star (e.g. practice marathon gut training on long runs during shorter sub-goal blocks).
   - Adapt sports-science reference ranges to this runner and explain why: daily carbs `~5-10 g/kg` periodized by load; intra-run carbs `~60-90 g/h` on long/hard sessions with gut training; fluid `~400-800 ml/h` + sodium adjusted for heat/humidity; post-run carbs + protein within ~60 min.

2. **Output (Chat Markdown — practical timing, rates, and food options, not rigid meal plans)**:
   1. **Core Nutrition Strategy**: fueling objective matched to upcoming load and conditions.
   2. **Key Fueling Targets**: daily carbs (`g/kg`), intra-run carbs (`g/h`), and fluid/sodium targets.
   3. **Actionable Fueling Directives**: pre-run, intra-workout, and post-run recovery guidance tied to specific upcoming sessions.