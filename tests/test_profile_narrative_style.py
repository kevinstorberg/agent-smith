from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from services.meetings import profile_fields
from services.personas import assessment
from tests.test_meeting_memory_agent import call, model as model


def sample():
    row = {"id": str(uuid4()), "display_name": "Alex", "section_notes": {}, "section_evidence": {}}
    claims = [{"id": f"claim-{index}", "meeting_id": "saved-meeting", "effective_content": content,
               "evidence": [{"segment_id": f"segment-{index}", "quote": content}]}
              for index, content in enumerate(("Gives detailed operational directions.", "Sets priorities for owners."))]
    sections = {key: {"status": "insufficient_evidence", "text": "", "claim_ids": []} for key in profile_fields.SECTION_FIELDS}
    sections["development_areas"] = {"status": "supported", "text": "Could develop outcome-based delegation to give owners more autonomy.",
                                     "claim_ids": [claim["id"] for claim in claims]}
    return row, claims, sections


@pytest.mark.parametrize("text", ["Evidence: segment-1 shows detailed delegation.", "See https://example.invalid/meeting for the interaction.",
                                 "This follows segment-42 from the meeting."])
def test_assessment_citations_belong_in_structured_evidence_not_narrative(text):
    row, claims, sections = sample()
    sections["development_areas"]["text"] = text
    with pytest.raises(ValueError, match="citations"):
        assessment.validate_output(row, claims, sections)


@pytest.mark.asyncio
async def test_react_repairs_event_citations_into_high_level_analysis_with_separate_support(model):
    row, claims, sections = sample()
    event_text = {**sections, "development_areas": {**sections["development_areas"], "text": "Evidence: segment-1 describes an interaction."}}
    instance, _ = model([call("stage_assessment", sections=event_text), call("stage_assessment", sections=sections), AIMessage(content="Done")])
    result = await assessment.synthesize(row, claims)
    assert result["sections"]["development_areas"] == sections["development_areas"]
    assert any(isinstance(message, ToolMessage) and "citations" in message.content for message in instance.seen[-1])
