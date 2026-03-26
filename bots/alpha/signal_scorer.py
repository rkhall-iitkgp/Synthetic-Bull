from shared.config import ALPHA_SCORE_THRESHOLD

# Updated weights: 5 indicators with price_deviation replacing some RSI weight
WEIGHTS = {
    "ema": 0.25,
    "rsi": 0.15,
    "macd": 0.25,
    "bollinger": 0.15,
    "price_deviation": 0.20,
}


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
            total_indicators = len(WEIGHTS)
            if decision == "BUY":
                agree = sum(1 for k in WEIGHTS if float(votes.get(k, 0.0)) > 0)
            else:
                agree = sum(1 for k in WEIGHTS if float(votes.get(k, 0.0)) < 0)
            confidence = min(max(agree / total_indicators, 0.0), 1.0)

        return {
            "score": float(score),
            "decision": decision,
            "confidence": float(confidence),
            "votes": votes,
        }
