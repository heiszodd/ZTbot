from __future__ import annotations

from datetime import date

import db

NARRATIVES = {
  "dog_coins": ["dog","doge","shib","inu","puppy","woof","bone","paw"],
  "frog_coins": ["frog","pepe","kek","ribbit","toad","amphibian"],
  "cat_coins": ["cat","kitty","meow","nyan","felix","whiskers"],
  "political": ["trump","biden","maga","vote","president","election","kamala"],
  "ai_meta": ["ai","gpt","robot","neural","llm","artificial","intelligence"],
  "food_coins": ["pizza","burger","taco","sushi","cake","donut","sandwich"],
  "animal_misc": ["panda","penguin","hamster","monkey","ape","bear","bull"],
  "chad_culture": ["chad","wojak","based","cope","wagmi","gm","ngmi","degen"],
  "celebrity": ["elon","musk","trump","bezos","gates","snoop","kanye"],
  "space": ["moon","mars","rocket","nasa","space","galaxy","cosmos"]
}


def detect_narrative(token_name: str, description: str) -> str:
    hay = f"{token_name or ''} {description or ''}".lower()
    best, best_hits = "other", 0
    for k, kws in NARRATIVES.items():
        hits = sum(1 for kw in kws if kw in hay)
        if hits > best_hits:
            best, best_hits = k, hits
    return best


def update_narrative_trends(token_data: dict, moon_score: int, risk_score: int) -> None:
    narrative = detect_narrative(token_data.get("name", ""), token_data.get("description", ""))
    db.upsert_narrative_trend(narrative=narrative, week_start=date.today(), moon_score=moon_score, risk_score=risk_score, volume=float(token_data.get("volume_24h") or 0))


def get_hot_narratives(limit: int = 5) -> list:
    return db.get_hot_narratives(limit)


def get_cold_narratives() -> list:
    return db.get_cold_narratives()
