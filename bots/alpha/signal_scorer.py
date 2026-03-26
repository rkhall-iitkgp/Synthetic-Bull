from shared.config import ALPHA_SCORE_THRESHOLD

WEIGHTS = {"ema": 0.30, "rsi": 0.25, "macd": 0.25, "bollinger": 0.20}


class SignalScorer:
    def score(self, votes: dict) -> dict:
        score = 0.0
        for key, weight in WEIGHTS.items():
            score += float(votes.get(key, 0.0)) * weight

        if score > ALPHA_SCORE_THRESHOLD:
            decision = "BUY"
        elif score < -ALPHA_SCORE_THRESHOLD:
            decision = "SELL"
        else:
            decision = "HOLD"

        confidence = 0.0
        if decision != "HOLD":
            if decision == "BUY":
                agree = sum(1 for v in votes.values() if float(v) > 0)
            else:
                agree = sum(1 for v in votes.values() if float(v) < 0)
            confidence = min(max(agree / 4.0, 0.0), 1.0)

        return {
            "score": float(score),
            "decision": decision,
            "confidence": float(confidence),
            "votes": votes,
        }
