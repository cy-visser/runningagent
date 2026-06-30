import argparse
import json
import sys

def calculate_nutrition(weight_kg, height_cm, age_years, gender, weekly_mileage_km):
    # 1. Calculate Basal Metabolic Rate (BMR) using Mifflin-St Jeor
    if gender.lower() in ("male", "m"):
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years + 5.0
    else:
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years - 161.0
        
    # 2. Calculate Daily Caloric Needs (TDEE)
    tdee_baseline = bmr * 1.375
    daily_running_burn = (weight_kg * (weekly_mileage_km / 7.0)) * 1.036
    tdee_total = round(tdee_baseline + daily_running_burn, 2)
    
    # 3. Calculate Daily Macronutrients
    carbs_g = round(weight_kg * 6.0, 1)
    carbs_kcal = carbs_g * 4.0
    
    protein_g = round(weight_kg * 1.5, 1)
    protein_kcal = protein_g * 4.0
    
    fat_kcal = max(tdee_total - carbs_kcal - protein_kcal, 0.0)
    fat_g = round(fat_kcal / 9.0, 1)
    
    # 4. Calculate Specific Workout Fueling Targets (Based on body weight)
    pre_workout_carbs_g = round(weight_kg * 1.0, 1)  # 1g per kg
    recovery_carbs_g = round(weight_kg * 1.0, 1)     # 1g per kg
    recovery_protein_g = round(weight_kg * 0.3, 1)   # 0.3g per kg (~3:1 ratio)
    
    workout_fueling = {
        "pre_workout": {
            "timeframe": "1 to 2 hours before run",
            "carbohydrates_grams": pre_workout_carbs_g,
            "guideline": "High-carb, low-fat, low-fiber snack (e.g., toast with banana, oatmeal)."
        },
        "intra_workout": {
            "applicability": "For runs longer than 75 minutes",
            "carbohydrates_per_hour_grams": "60 to 90",
            "fluid_per_hour_ml": "400 to 800",
            "guideline": "Consume easy-to-digest carbs (gels, chews, sports drinks) starting 30 mins in."
        },
        "recovery_post_workout": {
            "timeframe": "Within 30 to 60 minutes after finishing",
            "carbohydrates_grams": recovery_carbs_g,
            "protein_grams": recovery_protein_g,
            "ratio": "approx 3:1 carb-to-protein",
            "guideline": "Refuel immediately to restore glycogen and repair muscles (e.g., chocolate milk, recovery shake, chicken & rice)."
        }
    }
    
    return {
        "bmr_kcal": round(bmr, 2),
        "tdee_kcal": tdee_total,
        "daily_running_burn_avg_kcal": round(daily_running_burn, 2),
        "daily_macronutrients": {
            "carbohydrates": {"grams": carbs_g, "kcal": round(carbs_kcal, 2), "percentage": round((carbs_kcal / tdee_total) * 100, 1)},
            "protein": {"grams": protein_g, "kcal": round(protein_kcal, 2), "percentage": round((protein_kcal / tdee_total) * 100, 1)},
            "fat": {"grams": fat_g, "kcal": round(fat_kcal, 2), "percentage": round((fat_kcal / tdee_total) * 100, 1)}
        },
        "workout_fueling_targets": workout_fueling
    }

def main():
    parser = argparse.ArgumentParser(description="Calculate runner nutrition and fueling targets.")
    parser.add_argument("--weight", type=float, required=True, help="Weight in kg")
    parser.add_argument("--height", type=float, required=True, help="Height in cm")
    parser.add_argument("--age", type=int, required=True, help="Age in years")
    parser.add_argument("--gender", type=str, required=True, help="male or female")
    parser.add_argument("--mileage", type=float, required=True, help="Weekly mileage in km")
    
    args = parser.parse_args()
    
    try:
        results = calculate_nutrition(
            weight_kg=args.weight,
            height_cm=args.height,
            age_years=args.age,
            gender=args.gender,
            weekly_mileage_km=args.mileage
        )
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
