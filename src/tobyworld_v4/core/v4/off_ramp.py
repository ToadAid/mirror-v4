# off_ramp.py
import re

SOFT_KEYWORDS = [
    "thanks", "thank you", "goodbye", "farewell", "all set", "that's it",
    "the end", "finished", "conclude", "over", "rest"
]

HARD_PHRASES = [
    "dialogue is complete", "reflection is final", "journey is complete",
    "i'm done", "i am done", "final lesson is integrated",
    "we can stop here", "let the pond rest", "no further questions", "that is all"
]

EXIT_THRESHOLD = 3

# NEW: pure gratitude detector
_PURE_GRATITUDE_RX = re.compile(
    r"^\s*(thanks|thank you|thanks mirror|thank you mirror)[\s.!?]*$",
    re.IGNORECASE,
)

def get_exit_score(user_input: str) -> int:
    text = (user_input or "").strip().lower()
    if _PURE_GRATITUDE_RX.match(text):
        return 5  # immediate exit for short gratitude
    for phrase in HARD_PHRASES:
        if phrase in text:
            return 5
    score = 0
    for kw in SOFT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            score += 1
    return score

def should_exit_gracefully(user_input: str) -> bool:
    return get_exit_score(user_input) >= EXIT_THRESHOLD

def generate_final_farewell(final_affirmation: str) -> str:
    return (
        "Traveler, the reflection rests. May the pond remain within you. 🪞🌊🍃🌀"
        if not final_affirmation
        else (
            f"Traveler, the Mirror acknowledges your final words: '{final_affirmation.strip()}'\n\n"
            "The reflection is complete. The wisdom is integrated, and the stillness is carried within. "
            "Farewell, Traveler. May the stillness of the pond always guide your path. 🪞🌊🍃🌀"
        )
    )
