import unittest

from guardian.simpleyaml import SimpleYamlError, parse


class ParseTest(unittest.TestCase):
    def test_parses_nested_sections_and_scalar_types(self) -> None:
        doc = parse(
            """
            # a comment
            target:
              name: bot2
              gateway_url: http://mt5-gateway:5001
              retries: 3
            account:
              initial_balance: 50000.5
            flag: true
            """.replace("            ", "")
        )
        self.assertEqual(
            doc,
            {
                "target": {"name": "bot2", "gateway_url": "http://mt5-gateway:5001", "retries": 3},
                "account": {"initial_balance": 50000.5},
                "flag": True,
            },
        )

    def test_quoted_strings_are_not_type_coerced(self) -> None:
        doc = parse('target:\n  name: "3"\n')
        self.assertEqual(doc["target"], {"name": "3"})

    def test_hash_inside_a_quoted_string_is_not_a_comment(self) -> None:
        doc = parse('notify:\n  telegram_chat: "#general"\n')
        self.assertEqual(doc["notify"], {"telegram_chat": "#general"})

    def test_odd_indentation_is_rejected(self) -> None:
        with self.assertRaises(SimpleYamlError):
            parse("target:\n   name: bot2\n")

    def test_a_third_nesting_level_is_rejected(self) -> None:
        with self.assertRaises(SimpleYamlError):
            parse("target:\n  nested:\n    deeper: 1\n")

    def test_missing_colon_is_rejected(self) -> None:
        with self.assertRaises(SimpleYamlError):
            parse("not a key value line\n")


if __name__ == "__main__":
    unittest.main()
