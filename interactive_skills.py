# ==========================================
# N.O.V.A. - Interactive Multi-Turn Skills & Games Router
# Multi-turn conversational mini-games (Trivia, Math Quiz, Coin Flip, Riddles)
# with short-term dialogue context management and seamless loop return
# Fully compatible with Python 3.14.7 runtime
# ==========================================
import random
import re
from typing import Tuple, Optional, Dict, Any, List, Callable
from sound_utils import play_chime

# -------------------------------------------------------------
# 1. TRIVIA CHALLENGE SKILL
# -------------------------------------------------------------
TRIVIA_QUESTIONS = [
    {
        "q": "What was the name of the first artificial Earth satellite launched in 1957?",
        "answers": ["sputnik", "sputnik 1", "sputnik one"],
        "hint": "It was launched by the Soviet Union and means 'traveler' in Russian.",
        "fact": "Sputnik 1 orbited Earth for three weeks before its batteries ran out."
    },
    {
        "q": "Who is credited with creating the Python programming language in 1991?",
        "answers": ["guido van rossum", "guido", "van rossum"],
        "hint": "He is a Dutch programmer named Guido.",
        "fact": "He named Python after the British comedy troupe Monty Python."
    },
    {
        "q": "What planet in our solar system has the highest surface temperature?",
        "answers": ["venus"],
        "hint": "It's the second planet from the Sun, enveloped in thick carbon dioxide clouds.",
        "fact": "Venus reaches scorching surface temperatures of approximately 465 degrees Celsius."
    },
    {
        "q": "In computer science, what do the letters in CPU stand for?",
        "answers": ["central processing unit"],
        "hint": "It is the primary electronic circuitry that executes instructions.",
        "fact": "The modern CPU executes billions of machine instructions every second."
    },
    {
        "q": "What is the speed of light in a vacuum, rounded to the nearest thousand kilometers per second?",
        "answers": ["300000", "three hundred thousand", "300,000", "300 thousand"],
        "hint": "Three times ten to the eighth power meters per second.",
        "fact": "Light takes approximately 8 minutes and 20 seconds to travel from the Sun to Earth."
    },
    {
        "q": "What year was the World Wide Web introduced to the public by Tim Berners-Lee?",
        "answers": ["1991", "nineteen ninety one"],
        "hint": "It happened in the early nineties.",
        "fact": "The first website went live at CERN in August 1991."
    },
    {
        "q": "Which element on the periodic table has the chemical symbol Au?",
        "answers": ["gold"],
        "hint": "It comes from the Latin word 'aurum'.",
        "fact": "Gold is virtually indestructible and does not tarnish or corrode."
    }
]

class TriviaSkill:
    def __init__(self, num_rounds: int = 3):
        self.num_rounds = num_rounds
        self.current_round = 0
        self.score = 0
        self.deck = random.sample(TRIVIA_QUESTIONS, min(num_rounds, len(TRIVIA_QUESTIONS)))
        self.awaiting_answer = False

    def start(self) -> str:
        self.current_round = 1
        self.score = 0
        self.awaiting_answer = True
        q_data = self.deck[self.current_round - 1]
        play_chime("ping")
        return (
            f"Tactical Trivia initiated, Boss. {self.num_rounds} rounds on the docket. "
            f"Round 1: {q_data['q']}"
        )

    def handle_turn(self, query: str) -> Tuple[str, bool]:
        """Returns: (response_text, is_finished)"""
        q_clean = query.lower().strip()
        q_data = self.deck[self.current_round - 1]

        # Check for hint request
        if "hint" in q_clean:
            return f"Intel hint, Boss: {q_data['hint']} What is your answer?", False

        # Evaluate answer
        is_correct = any(ans in q_clean for ans in q_data["answers"])

        if is_correct:
            self.score += 1
            play_chime("success")
            feedback = f"Affirmative, Boss! That is correct. {q_data['fact']}"
        else:
            play_chime("error")
            correct_ans = q_data["answers"][0].title()
            feedback = f"Negative, Boss. The target answer was {correct_ans}. {q_data['fact']}"

        # Check if more rounds remain
        if self.current_round < self.num_rounds:
            self.current_round += 1
            next_q = self.deck[self.current_round - 1]["q"]
            return f"{feedback} Moving to Round {self.current_round}: {next_q}", False
        else:
            # Game complete
            play_chime("alert")
            final_msg = (
                f"{feedback} Challenge completed, Boss! Your tactical score is {self.score} out of {self.num_rounds}. "
                f"{'Flawless operational accuracy.' if self.score == self.num_rounds else 'Solid engagement.'} "
                "Returning to main command loop."
            )
            return final_msg, True


# -------------------------------------------------------------
# 2. TACTICAL MATH QUIZ SKILL
# -------------------------------------------------------------
class MathQuizSkill:
    def __init__(self, num_rounds: int = 3):
        self.num_rounds = num_rounds
        self.current_round = 0
        self.score = 0
        self.current_answer = 0

    def _generate_problem(self) -> Tuple[str, int]:
        op = random.choice(["+", "-", "*"])
        if op == "+":
            a, b = random.randint(10, 50), random.randint(10, 50)
            return f"What is {a} plus {b}?", a + b
        elif op == "-":
            a = random.randint(30, 99)
            b = random.randint(10, a)
            return f"What is {a} minus {b}?", a - b
        else:
            a, b = random.randint(3, 12), random.randint(3, 12)
            return f"What is {a} multiplied by {b}?", a * b

    def start(self) -> str:
        self.current_round = 1
        self.score = 0
        prob_text, self.current_answer = self._generate_problem()
        play_chime("ping")
        return f"Mental math drill active, Boss. {self.num_rounds} calculations. Round 1: {prob_text}"

    def handle_turn(self, query: str) -> Tuple[str, bool]:
        numbers = re.findall(r'-?\d+', query)
        user_num = int(numbers[0]) if numbers else None

        # Convert simple spoken words if no digits
        word_to_num = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
            "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "hundred": 100
        }
        if user_num is None:
            for w, n in word_to_num.items():
                if w in query.lower():
                    user_num = n
                    break

        if user_num is None:
            return f"I didn't detect a numeric calculation, Boss. What is your numerical answer?", False

        is_correct = (user_num == self.current_answer)
        if is_correct:
            self.score += 1
            play_chime("success")
            feedback = "Direct hit, Boss! Correct."
        else:
            play_chime("error")
            feedback = f"Calculation off target. The exact value was {self.current_answer}."

        if self.current_round < self.num_rounds:
            self.current_round += 1
            prob_text, self.current_answer = self._generate_problem()
            return f"{feedback} Round {self.current_round}: {prob_text}", False
        else:
            play_chime("alert")
            return (
                f"{feedback} Math drill complete, Boss. Final precision: {self.score} of {self.num_rounds}. "
                "Resuming regular command monitor."
            ), True


# -------------------------------------------------------------
# 3. COIN FLIP & ODDS SKILL
# -------------------------------------------------------------
class CoinFlipSkill:
    def __init__(self):
        self.state = "awaiting_call" # 'awaiting_call' or 'awaiting_play_again'

    def start(self) -> str:
        self.state = "awaiting_call"
        play_chime("ping")
        return "Quantum coin toss initialized, Boss. Call it in the air: Heads or Tails?"

    def handle_turn(self, query: str) -> Tuple[str, bool]:
        q = query.lower()
        if self.state == "awaiting_call":
            if "head" in q:
                user_call = "heads"
            elif "tail" in q:
                user_call = "tails"
            else:
                return "Make your call, Boss: Heads or Tails?", False

            outcome = random.choice(["heads", "tails"])
            play_chime("ping")
            won = (user_call == outcome)
            if won:
                play_chime("success")
                result_speech = f"Coin is in the air... and it landed on {outcome.capitalize()}! Tactical victory, Boss. You called it."
            else:
                play_chime("error")
                result_speech = f"Coin is in the air... and it landed on {outcome.capitalize()}. House edge takes this one, Boss."

            self.state = "awaiting_play_again"
            return f"{result_speech} Would you like another toss, or return to base?", False

        elif self.state == "awaiting_play_again":
            if any(w in q for w in ["yes", "again", "flip", "toss", "sure", "one more"]):
                self.state = "awaiting_call"
                return "Coin is ready. Call it: Heads or Tails?", False
            else:
                return "Understood, Boss. Closing coin toss and returning to main system loop.", True

        return "Returning to main assistant loop, Boss.", True


# -------------------------------------------------------------
# 4. TACTICAL RIDDLE SKILL
# -------------------------------------------------------------
RIDDLES = [
    {
        "riddle": "I have branches, but no fruit, trunk or leaves. What am I?",
        "answers": ["bank", "a bank"],
        "hint": "Think of financial or river terms."
    },
    {
        "riddle": "What can travel all around the world while remaining in the same corner?",
        "answers": ["stamp", "a stamp", "postage stamp"],
        "hint": "It sticks to an envelope."
    },
    {
        "riddle": "I speak without a mouth and hear without ears. I have no body, but I come alive with wind. What am I?",
        "answers": ["echo", "an echo"],
        "hint": "You might hear me in a canyon or cave."
    }
]

class RiddleSkill:
    def __init__(self):
        self.riddle_data = random.choice(RIDDLES)
        self.attempts = 0

    def start(self) -> str:
        self.attempts = 0
        play_chime("ping")
        return f"Tactical enigma online, Boss: {self.riddle_data['riddle']}"

    def handle_turn(self, query: str) -> Tuple[str, bool]:
        q = query.lower().strip()
        if "give up" in q or "tell me" in q:
            ans = self.riddle_data["answers"][0].title()
            return f"The enigma solution is: {ans}. Returning to main loop, Boss.", True

        if "hint" in q:
            return f"Decryption hint: {self.riddle_data['hint']} What is your answer, Boss?", False

        if any(ans in q for ans in self.riddle_data["answers"]):
            play_chime("success")
            return f"Code cracked, Boss! That is correct. Returning to tactical monitor.", True

        self.attempts += 1
        if self.attempts >= 3:
            ans = self.riddle_data["answers"][0].title()
            return f"Attempt limit reached. The solution was {ans}. Returning to main loop, Boss.", True
        else:
            play_chime("error")
            return f"Negative, Boss. That is not it. You have {3 - self.attempts} attempts remaining, or ask for a hint.", False


# -------------------------------------------------------------
# MASTER SKILL ROUTER & SESSION MANAGER
# -------------------------------------------------------------
class SkillRouter:
    def __init__(self):
        self.active_skill: Optional[Any] = None
        self.skill_name: str = ""

    def is_session_active(self) -> bool:
        """True if user is currently inside an active multi-turn game."""
        return self.active_skill is not None

    def check_activation(self, query: str) -> Tuple[bool, str]:
        """
        Detects if user speech query triggers the launch of a conversational mini-game.
        """
        q = query.lower().strip()

        # Trivia
        if any(p in q for p in ["play trivia", "start trivia", "trivia game", "trivia challenge", "let's do trivia"]):
            self.active_skill = TriviaSkill(num_rounds=3)
            self.skill_name = "Trivia"
            return True, self.active_skill.start()

        # Math Quiz
        if any(p in q for p in ["math quiz", "math game", "mental math", "math challenge", "test my math"]):
            self.active_skill = MathQuizSkill(num_rounds=3)
            self.skill_name = "MathQuiz"
            return True, self.active_skill.start()

        # Coin Flip
        if any(p in q for p in ["flip a coin", "toss a coin", "coin flip", "flip coin", "heads or tails"]):
            self.active_skill = CoinFlipSkill()
            self.skill_name = "CoinFlip"
            return True, self.active_skill.start()

        # Riddle
        if any(p in q for p in ["tell me a riddle", "give me a riddle", "riddle me this", "play riddles"]):
            self.active_skill = RiddleSkill()
            self.skill_name = "Riddle"
            return True, self.active_skill.start()

        return False, ""

    def process_turn(self, query: str) -> Tuple[str, bool]:
        """
        Routes current speech turn to the active conversational skill.
        Returns: (spoken_response, should_exit_session)
        """
        q = query.lower().strip()

        # Universal skill exit keywords
        if any(w == q or w in q for w in [
            "exit", "quit", "stop", "cancel", "nevermind", "end game", "stop game", "back to main", "abort"
        ]):
            self.active_skill = None
            self.skill_name = ""
            return "Exiting skill module and returning to main tactical command loop, Boss.", True

        # Process within active skill
        response, is_finished = self.active_skill.handle_turn(query)
        if is_finished:
            self.active_skill = None
            self.skill_name = ""
            return response, True

        return response, False

# Global singleton router
skill_router = SkillRouter()
