import unittest

from repojanitor.models import ModelPricing, TaskPacket, Usage
from repojanitor.provider import parse_json_content


class ModelPricingTests(unittest.TestCase):
    def test_estimates_cost_from_configured_rates(self):
        pricing = ModelPricing(
            input_per_million=1.0,
            cached_input_per_million=0.1,
            output_per_million=2.0,
        )
        usage = Usage(
            input_tokens=1_000_000,
            cached_input_tokens=800_000,
            output_tokens=100_000,
        )
        self.assertAlmostEqual(pricing.estimate(usage), 0.48)

    def test_missing_pricing_is_provider_neutral(self):
        self.assertEqual(ModelPricing().estimate(Usage(input_tokens=10_000)), 0.0)

    def test_rejects_unsafe_task_id(self):
        with self.assertRaises(ValueError):
            TaskPacket(id="../../escape", kind="test", title="Unsafe")

    def test_rejects_option_like_base_ref(self):
        with self.assertRaises(ValueError):
            TaskPacket(id="safe", kind="test", title="Unsafe", base_ref="--force")

    def test_parses_fenced_json_for_prompt_only_adapters(self):
        self.assertEqual(parse_json_content("```json\n{\"ok\": true}\n```"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
