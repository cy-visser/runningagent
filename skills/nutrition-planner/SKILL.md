---
name: nutrition-planner
description: Calculates daily caloric needs (TDEE), macronutrient splits, and specific pre/intra/post-workout fueling targets for runners.
---

# Nutrition & Fueling Planner Skill

You are now equipped with the Nutrition & Fueling Planner skill. Use this skill to provide expert, scientifically backed nutrition, daily meal planning, and workout fueling guidance to the runner.

## Core Coaching Protocols:

### 1. Daily Meal Planning ("What I should eat today")
When the runner asks what they should eat today:
1.  Run the `calculate_nutrition.py` script to get their daily TDEE and macronutrient targets.
2.  Translate these targets into a **personalized, practical daily meal plan** consisting of:
    *   **Breakfast**: A high-carbohydrate, moderate-protein meal optimized for pre-run energy or morning recovery, tailored to their training schedule and preferences.
    *   **Lunch**: A balanced meal combining complex carbohydrates, high-quality lean protein, and healthy fats to support recovery and sustain energy.
    *   **Dinner**: A nutrient-dense recovery meal rich in proteins, complex carbohydrates, and micronutrients to support muscle repair, glycogen replenishment, and overall health.
    *   **Snacks**: Easy-to-digest, carbohydrate-rich snacks strategically timed around training sessions.
3.  Ensure the food recommendations are practical, whole-food based, easy to digest, and offer variety (do not limit yourself to standard examples like oatmeal or chicken; use your expertise to provide diverse, delicious options).

### 2. Fueling for Big Workouts (Long Runs / Intense Sessions)
When the runner has a "big workout" (e.g., a long run > 75 mins, or a heavy speed session):
1.  Run the `calculate_nutrition.py` script to get their weight-specific fueling targets.
2.  Explain the **three phases of workout fueling**:
    *   **Pre-Workout (1-2 hours before)**: High-carb, low-fiber, low-fat snack to top off liver glycogen.
    *   **Intra-Workout (During the run)**: Consuming fast-acting carbs (gels, chews, sports drinks) and fluids to maintain blood glucose and hydration.
    *   **Recovery (Within 30-60 mins after)**: A 3:1 or 4:1 carb-to-protein ratio to rebuild muscle and replenish muscle glycogen.
3.  Provide the exact gram targets calculated by the script and suggest real-world examples (e.g., "Take 2 gels per hour", "Drink a recovery shake with 60g carbs and 20g protein").

## How to Run the Calculator:
*   Call the `run_skill_script` tool with `skill_name="nutrition_planner"` and `file_path="scripts/calculate_nutrition.py"`.
*   Pass the runner's metrics: `--weight`, `--height`, `--age`, `--gender`, and `--mileage`.
