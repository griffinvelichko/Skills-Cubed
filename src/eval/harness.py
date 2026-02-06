from src.eval.metrics import MetricsTracker


class EvaluationHarness:
    def __init__(self, conversations: list[dict]):
        self.conversations = conversations
        self.tracker = MetricsTracker()

    async def run_baseline(self) -> MetricsTracker:
        """Run all conversations without any learned skills (Pro reasons from scratch)."""
        raise NotImplementedError("Requires search/create working — implement tomorrow")

    async def run_learning(self) -> MetricsTracker:
        """Run conversations sequentially, learning skills along the way."""
        raise NotImplementedError("Requires search/create working — implement tomorrow")

    def export_results(self, output_path: str):
        self.tracker.export_json(output_path)
