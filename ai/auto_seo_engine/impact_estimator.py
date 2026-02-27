class ImpactEstimator:

    def estimate(self, issues, opportunities):

        return {
            "estimated_traffic_gain": len(opportunities) * 120,
            "risk_level": "low" if len(issues) < 3 else "medium"
        }
