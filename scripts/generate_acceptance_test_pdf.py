"""Generate a small, synthetic, non-confidential PDF for real end-to-end
chatbot acceptance testing. Content is fabricated for this purpose only and
is not derived from any internal or confidential document.
"""

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "input" / "acceptance_test_pump_manual.pdf"

CONTENT = [
    ("h1", "Synthetic Centrifugal Pump Reference Manual"),
    (
        "p",
        "This document is a synthetic reference manual created solely for automated "
        "acceptance testing of the document-ingestion chatbot. It describes a "
        "fictional centrifugal pump model designated SP-100 and contains no "
        "confidential or proprietary information.",
    ),
    ("h2", "1. Overview"),
    (
        "p",
        "The SP-100 is a single-stage, end-suction centrifugal pump intended for "
        "general industrial water transfer applications. Its rated flow is 250 "
        "cubic meters per hour at a total dynamic head of 45 meters, driven by a "
        "75 kilowatt electric motor operating at 2950 revolutions per minute.",
    ),
    ("h2", "2. Maintenance Schedule"),
    (
        "p",
        "Routine maintenance of the SP-100 pump requires inspection of the "
        "mechanical seal every 2000 operating hours. Bearing lubrication must be "
        "performed every 4000 operating hours using ISO VG 68 grade oil. The "
        "impeller clearance should be checked annually and adjusted to remain "
        "within 0.3 to 0.5 millimeters.",
    ),
    ("h2", "3. Safety Precautions"),
    (
        "p",
        "Before performing any maintenance on the SP-100 pump, the operator must "
        "isolate electrical power at the motor control center and apply lockout "
        "tagout procedures. The pump casing must be depressurized and drained "
        "before the casing cover is removed. Only trained personnel should "
        "perform disassembly of the mechanical seal.",
    ),
    ("h2", "4. Troubleshooting"),
    (
        "p",
        "If the SP-100 pump exhibits excessive vibration, the most common causes "
        "are impeller imbalance, cavitation due to insufficient net positive "
        "suction head, or worn bearings. If discharge pressure is lower than "
        "expected, check for a partially closed suction valve, worn wear rings, "
        "or an air leak at the suction flange gasket.",
    ),
]

styles = getSampleStyleSheet()


def build() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT_PATH), pagesize=LETTER)
    story = []
    for kind, text in CONTENT:
        style = (
            styles["Title"] if kind == "h1" else styles["Heading2"] if kind == "h2" else styles["BodyText"]
        )
        story.append(Paragraph(text, style))
        story.append(Spacer(1, 0.15 * inch))
    doc.build(story)
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
