from accounts.models import Profile, MemoryItem
from ai.client import generate, retrieve, validate_citations, AIError
from .models import ChatMessage


def answer(session, question):
    profile, _ = Profile.objects.get_or_create(user=session.owner)
    memory = (
        list(MemoryItem.objects.filter(owner=session.owner).values("text", "kind")) if profile.memory_enabled else []
    )
    sources = retrieve(session.owner, session.course, question)
    if session.mode != "guidance" and not sources:
        result = {
            "answer": "Your confirmed notes do not contain enough information for this question. Upload or confirm relevant material, or try more specific terms.",
            "citations": [],
        }
    else:
        instruction = 'Return JSON {"answer": string, "citations": [{"page_id": integer, "quote": exact source substring}]}. Answer in the preferred language. '
        instruction += (
            "Give general study/career guidance; clearly label it as general guidance, not grounded in notes."
            if session.mode == "guidance"
            else 'Answer only from provided sources. Cite supporting quotes. If insufficient evidence, use answer "The notes do not contain enough information." and citations [].'
        )
        if session.mode == "tutor":
            instruction += " Explain step by step, then ask one check-for-understanding question."
        # Do not replay previous assistant responses: they may contain a now-deleted memory.
        result = generate(
            instruction, {"question": question, "sources": sources, "language": profile.language, "memory": memory}
        )
        if not isinstance(result.get("answer"), str) or not result["answer"].strip():
            raise AIError("AI returned an empty answer.")
        if session.mode != "guidance" and result["answer"] != "The notes do not contain enough information.":
            result["citations"] = validate_citations(result.get("citations"), sources)
        else:
            result["citations"] = []
    ChatMessage.objects.create(session=session, role="user", text=question)
    message = ChatMessage.objects.create(
        session=session, role="assistant", text=result["answer"], citations=result["citations"]
    )
    return message
