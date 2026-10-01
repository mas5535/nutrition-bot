#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
?????? ?????? ??????? ???????? ??????
?? ???? ??? ?????? ??? ??? ? ??? ??????
????: US DRI - National Academies of Sciences
"""

import json
import os
import sys
from typing import Dict, Any, Optional


class NutritionCalculator:
    """???? ???? ?????? ??????? ????????"""

    def __init__(self, db_path: str = "nutrition_db.json"):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"???? ??????? ???? ???: {db_path}")
        with open(db_path, "r", encoding="utf-8") as f:
            self.db: Dict[str, Any] = json.load(f)

    # ---------- ????? ???? ----------
    @staticmethod
    def get_age_range(age: int) -> str:
        """????? ?? ?? ???? ???? ???"""
        if age < 1:  return "0-1"
        if age < 4:  return "1-3"
        if age < 9:  return "4-8"
        if age < 14: return "9-13"
        if age < 19: return "14-18"
        if age < 31: return "19-30"
        if age < 51: return "31-50"
        if age < 71: return "51-70"
        return "71+"

    @staticmethod
    def calculate_bmr(weight: float, height: float, age: int, gender: str) -> float:
        """?????? ????????? ???? (BMR) ?? ????? Mifflin-St Jeor"""
        base = (10 * weight) + (6.25 * height) - (5 * age)
        return base + 5 if gender == "male" else base - 161

    def calculate_tdee(self, bmr: float, activity_key: str) -> float:
        """?????? ????? ?? ?????? (TDEE)"""
        multiplier = self.db["activity_levels"][activity_key]["multiplier"]
        return bmr * multiplier

    # ---------- ?????? ???????????? ----------
    def calculate_macros(self, weight: float, tdee: float,
                         activity_key: str, gender: str, age: int) -> Dict[str, Any]:
        """?????? ???????? ????? ?????????? ? ????"""
        protein_g_per_kg = self.db["macros"]["protein_g_per_kg"][activity_key]
        protein_g  = round(weight * protein_g_per_kg, 1)
        protein_kcal = protein_g * self.db["macros"]["calories_per_gram"]["protein"]

        fat_min_pct = self.db["macros"]["fat_percent_of_calories"]["min"]
        fat_max_pct = self.db["macros"]["fat_percent_of_calories"]["max"]
        fat_kcal_mid = tdee * ((fat_min_pct + fat_max_pct) / 2 / 100)
        fat_g = round(fat_kcal_mid / self.db["macros"]["calories_per_gram"]["fat"], 1)

        carb_kcal = tdee - protein_kcal - fat_kcal_mid
        carb_g = round(max(carb_kcal, 0) / self.db["macros"]["calories_per_gram"]["carb"], 1)

        fiber_key = "under_51" if age < 51 else "over_51"
        fiber_g = self.db["macros"]["fiber_g"][gender][fiber_key]

        water_key = "19+" if age >= 19 else "14-18"
        water_l = self.db["macros"]["water_liters"][gender].get(water_key, 2.5)

        return {
            "protein_g": protein_g,
            "protein_kcal": round(protein_kcal),
            "fat_g": fat_g,
            "fat_range_g": (
                round((tdee * fat_min_pct / 100) / 9, 1),
                round((tdee * fat_max_pct / 100) / 9, 1),
            ),
            "carb_g": carb_g,
            "carb_range_g": (
                round((tdee * 0.45) / 4, 1),
                round((tdee * 0.65) / 4, 1),
            ),
            "fiber_g": fiber_g,
            "water_l": water_l,
        }

    # ---------- ??????? DRI ?? ???? ???? ----------
    def get_dri(self, nutrient: Dict[str, Any], gender: str, age: int,
                life_stage: str = "normal") -> Optional[float]:
        """??????? ????? ????????? ?????? ???? ?? ???? ????"""
        age_range = self.get_age_range(age)
        dri_table = nutrient.get("dri", {})

        if life_stage in ("pregnancy", "lactation") and life_stage in dri_table:
            table = dri_table[life_stage]
        else:
            table = dri_table.get(gender, {})

        # ?????? ??????
        if age_range in table:
            return table[age_range]

        # ?????? ???????? ?????? (????? "14+" ?? "19-50")
        for key, value in table.items():
            if key.endswith("+") and age >= int(key[:-1]):
                return value
            if "-" in key:
                try:
                    lo, hi = key.split("-")
                    if int(lo) <= age <= int(hi):
                        return value
                except ValueError:
                    continue
        return None

    # ---------- ??????? ????? ????? ----------
    def suggest_foods(self, nutrient: Dict[str, Any],
                      required_amount: float) -> list:
        """
        ???? ?? ???? ????? ????? ??? ???? ???? ?? ? ???? ???? ?? ?????? ??????
        ?? ???? ?????? ????? ???.
        """
        suggestions = []
        sources = sorted(nutrient["food_sources"],
                         key=lambda x: x["per_100g"], reverse=True)[:3]
        for src in sources:
            if src["per_100g"] <= 0:
                continue
            grams_needed = (required_amount / src["per_100g"]) * 100
            suggestions.append({
                "food": src["name"],
                "grams_needed": round(grams_needed, 1),
                "per_100g": src["per_100g"],
            })
        return suggestions

    # ---------- ????? ???? ----------
    def build_report(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """???? ????? ???? ??????? ??????"""
        gender    = user["gender"]
        age       = user["age"]
        weight    = user["weight_kg"]
        height    = user["height_cm"]
        activity  = user["activity"]
        life_stage = user.get("life_stage", "normal")

        bmr  = self.calculate_bmr(weight, height, age, gender)
        tdee = self.calculate_tdee(bmr, activity)
        macros = self.calculate_macros(weight, tdee, activity, gender, age)

        nutrients_report = []
        for nutrient in self.db["nutrients"]:
            dri = self.get_dri(nutrient, gender, age, life_stage)
            if dri is None:
                continue
            entry = {
                "id": nutrient["id"],
                "name": nutrient["name"],
                "unit": nutrient["unit"],
                "required": dri,
                "ul": nutrient.get("ul", {}).get(gender),
                "food_suggestions": self.suggest_foods(nutrient, dri),
            }
            nutrients_report.append(entry)

        return {
            "user": user,
            "bmr_kcal": round(bmr),
            "tdee_kcal": round(tdee),
            "macros": macros,
            "nutrients": nutrients_report,
        }


# ================================================================
#                        ???? ?????? ????
# ================================================================
def ask_float(prompt: str, min_val: float, max_val: float) -> float:
    while True:
        try:
            value = float(input(prompt).strip())
            if min_val <= value <= max_val:
                return value
            print(f"  ?? ????? ???? ??? {min_val} ? {max_val} ????.")
        except ValueError:
            print("  ?? ????? ?? ??? ????? ???? ??.")


def ask_int(prompt: str, min_val: int, max_val: int) -> int:
    while True:
        try:
            value = int(input(prompt).strip())
            if min_val <= value <= max_val:
                return value
            print(f"  ?? ????? ???? ??? {min_val} ? {max_val} ????.")
        except ValueError:
            print("  ?? ????? ?? ??? ???? ???? ??.")


def ask_choice(prompt: str, choices: Dict[str, str]) -> str:
    print(prompt)
    keys = list(choices.keys())
    for i, key in enumerate(keys, 1):
        print(f"  {i}) {choices[key]}")
    while True:
        try:
            idx = int(input("??????: ").strip()) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print("  ?? ?????? ???????. ?????? ???? ??.")


def print_report(report: Dict[str, Any]) -> None:
    user = report["user"]
    line = "-" * 60

    print("\n" + "-" * 60)
    print("       ?? ????? ??????? ???????? ??????")
    print("-" * 60)
    print(f"  ??: {user['age']} ??? | ?????: "
          f"{'???' if user['gender']=='male' else '??'}")
    print(f"  ??: {user['height_cm']} cm | ???: {user['weight_kg']} kg")
    print(f"  ??? ??????: {user['activity_label']}")

    print("\n" + line)
    print("  ?? ????? ? ????????????")
    print(line)
    print(f"  ????????? ???? (BMR)   : {report['bmr_kcal']:,} ?????")
    print(f"  ????? ?? ?????? (TDEE) : {report['tdee_kcal']:,} ?????")
    m = report["macros"]
    print(f"  ???????                : {m['protein_g']} ??? "
          f"({m['protein_kcal']} ?????)")
    print(f"  ????                   : {m['fat_g']} ??? "
          f"(???? ????: {m['fat_range_g'][0]}–{m['fat_range_g'][1]} ???)")
    print(f"  ??????????             : {m['carb_g']} ??? "
          f"(???? ????: {m['carb_range_g'][0]}–{m['carb_range_g'][1]} ???)")
    print(f"  ????                   : {m['fiber_g']} ???")
    print(f"  ??                     : {m['water_l']} ????")

    print("\n" + line)
    print("  ?? ?????????? (?????????? ? ?????)")
    print(line)
    for n in report["nutrients"]:
        ul_text = f" | ?????? ????: {n['ul']} {n['unit']}" if n["ul"] else ""
        print(f"\n  ? {n['name']}: {n['required']} {n['unit']}{ul_text}")
        for fs in n["food_suggestions"]:
            print(f"      • {fs['food']}: ???? {fs['grams_needed']} ??? "
                  f"({fs['per_100g']} {n['unit']} ?? ??? ???)")

    print("\n" + "-" * 60)
    print("  ??  ??? ????? ????? ?????. ???? ????? ??? ?? ???? ????? ??.")
    print("-" * 60 + "\n")


def main():
    print("\n" + "-" * 60)
    print("   ?? ????? ???? ??????? ???????? ??????")
    print("-" * 60)

    try:
        calc = NutritionCalculator("nutrition_db.json")
    except FileNotFoundError as e:
        print(f"\n? ???: {e}")
        print("   ???? nutrition_db.json ?? ?? ???? ???? ???? ???.")
        sys.exit(1)

    # --- ?????? ??????? ????? ---
    age    = ask_int("\n?? (???): ", 1, 120)
    gender = ask_choice("\n?????:", {"male": "???", "female": "??"})
    height = ask_float("?? (?????????): ", 50, 250)
    weight = ask_float("??? (???????): ", 10, 400)

    activity_choices = {
        k: v["label"] for k, v in calc.db["activity_levels"].items()
    }
    activity = ask_choice("\n??? ?????? ??????:", activity_choices)

    life_stage = "normal"
    if gender == "female" and 14 <= age <= 50:
        choice = ask_choice(
            "\n????? ???????/??????:",
            {"normal": "????", "pregnancy": "??????", "lactation": "?????"}
        )
        life_stage = choice

    user = {
        "age": age,
        "gender": gender,
        "height_cm": height,
        "weight_kg": weight,
        "activity": activity,
        "activity_label": calc.db["activity_levels"][activity]["label"],
        "life_stage": life_stage,
    }

    report = calc.build_report(user)
    print_report(report)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n?? ?????? ????? ??.")