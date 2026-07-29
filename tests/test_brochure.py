from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.brochure import convert_pptx_batch_to_pdf


class BatchConversionTests(unittest.TestCase):
    def test_converts_presentations_in_order_with_one_process_per_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = []
            for name in ("first.pptx", "second.pptx", "third.pptx"):
                path = root / name
                path.write_bytes(b"pptx")
                inputs.append(str(path))

            output_dir = root / "pdf"

            def fake_run(command, **_kwargs):
                out_index = command.index("--outdir")
                destination = Path(command[out_index + 1])
                for source in command[out_index + 2:]:
                    source_path = Path(source)
                    (destination / f"{source_path.stem}.pdf").write_bytes(b"pdf")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("subprocess.run", side_effect=fake_run) as run:
                result = convert_pptx_batch_to_pdf(
                    "soffice",
                    inputs,
                    str(output_dir),
                    batch_size=2,
                )

            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                [Path(path).name for path in result],
                ["first.pdf", "second.pdf", "third.pdf"],
            )

    def test_rejects_non_positive_batch_size(self):
        with self.assertRaisesRegex(ValueError, "batch_size"):
            convert_pptx_batch_to_pdf("soffice", ["one.pptx"], ".", 0)


if __name__ == "__main__":
    unittest.main()
