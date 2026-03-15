import base64
import io
import json
import re

from pathlib import Path
from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB API limit
MAX_DIMENSION   = 1568               # Anthropic's recommended max

PROMPT_TEMPLATE = """You are an expert at creating Anki flashcards following best practices.

Analyze this textbook screenshot and create Anki flashcards from it.

RULES:
- Each card tests ONE concept. If the back needs more than 2 sentences, split it into multiple cards instead.
- Front: write how a curious student would actually ask it — conversational, not academic. "Why does X cause Y?" not "Describe the mechanism by which X results in Y."
- Front: never use passive voice or academic phrasing. Not "What is the mechanism by which..." or "How is X characterized by..." — just ask it directly.
- Back: 1–3 sentences max, plain english. Use jargon only when the jargon itself is what's being learned. Never use phrases like "as illustrated", "in the context of", or "with respect to".
- Never cram extra info into parentheses — if it's worth saying, give it its own sentence. A 3-sentence back with clear sentences is better than 1 sentence stuffed with parentheticals.
- If you are tempted to write a back longer than 3 sentences, stop — split it into multiple cards instead.
- For definitions: "What is [term]?" → one plain-english sentence
- For processes/steps: one card per step, written as a natural question
- For cause/effect: "What happens when X?" → short direct answer; add a reverse card if both directions are worth knowing
- For formulas: "What's the formula for [concept]?" → formula + what each variable means
- For lists: cloze-style ("The 3 types of X are: [A], [B], [C]") not one card per item
- Skip trivial or obvious facts
- Generate 1–8 cards depending on content density

EXAMPLES — study these before writing any cards:

BAD: front: "What does this show?" / back: "It shows the process of how neural networks learn through multiple complex mechanisms involving weights and gradients."
GOOD: front: "How does a neural network update its weights?" / back: "It uses backpropagation — nudging each weight based on how much it contributed to the error."

BAD: front: "Describe the role of the hippocampus in memory consolidation." / back: "The hippocampus plays a critical role in the consolidation of information from short-term to long-term memory, as illustrated by studies of patients with hippocampal lesions."
GOOD: front: "Why do hippocampal lesions cause amnesia for new memories?" / back: "The hippocampus converts short-term memories into long-term ones — damage stops that transfer cold."

BAD: front: "What is a model's vocabulary?" / back: "The set of all tokens a model can work with." — too vague: 'tokens' is unexplained and 'work with' tells you nothing about what the vocabulary does or why it matters.
GOOD: front: "What is a model's vocabulary?" / back: "The fixed list of tokens it knows — every word, word-fragment, and symbol it can read or write. Words outside the vocabulary get broken into smaller pieces that are in it." — explains what a token is and includes the key insight about unknown words being split.

If the screenshot contains a DIAGRAM, CHART, or FIGURE:
- Break the diagram into multiple cards, each testing one concept shown in the diagram.
- CRITICAL: the reviewer will NOT see the diagram when studying the front of the card. The front MUST be a standalone factual question that makes perfect sense without any image. Extract specific facts, numbers, or relationships from the diagram and ask about those directly.
- NEVER reference the chart, diagram, figure, graph, or image on the front. Do not use phrases like "in the chart", "the chart shows", "when looking at the chart", "what does the diagram illustrate", "what types does the chart distinguish", "according to this chart", or "according to the diagram". The front must read as a normal knowledge question.
- NEVER reference visual symbols from the diagram on the back either. Do not say "marked ×", "shown as circles", "the blue line", "the dashed curve", etc. The back must be pure text that makes sense without seeing any image.
- Front: you can append "(Diagram)" at the end to signal a diagram is on the back.
- DIAGRAM CARD EXAMPLES — study these carefully:
  BAD: "What does the 'LLM Parameter Evolution' chart show about how models changed from 2018 to 2026? (Diagram)" — references the chart as something the user is looking at.
  BAD: "When looking at a chart of LLM parameter evolution, what does it mean that the axis uses a log scale?" — the user cannot see any chart.
  BAD: "What are the two main types of LLM architectures the chart distinguishes between?" — references the chart.
  BAD: "Roughly when did MoE architectures start appearing in LLMs, according to this chart?" — "according to this chart" references the image. Just remove it and add (Diagram).
  BAD: "Which frontier models around 2024-2026 use MoE vs dense?" / "MoE models (marked ×) include GPT-4o... Dense models (circles) include..." — "around 2024-2026" only makes sense with the chart's axis, and "marked ×" / "circles" reference visual symbols the user can't see.
  GOOD: "Name some LLMs that use Mixture-of-Experts architecture. (Diagram)" / "GPT-4o, Gemini 1.5 Pro, GPT-5, and Claude 4.6 Opus all use MoE, routing each token to a subset of expert sub-networks."
  GOOD: "Roughly when did Mixture-of-Experts (MoE) architectures start appearing in LLMs? (Diagram)" / "Around 2021-2022, with models like GLaM and Switch Transformer."
  GOOD: "How many parameters did GPT-2 have, and when was it introduced? (Diagram)" / "1.5 billion parameters, introduced in February 2019."
  GOOD: "What are the three stages of compilation? (Diagram)" / "Lexing, parsing, and code generation."
- Back: a text explanation that fully answers the question. The diagram image is attached automatically, but the text must stand on its own — no references to visual elements like colors, symbols, or axis positions.
- Set is_image_card: true on EVERY card generated from a diagram so the image gets attached to all of them.
- If the screenshot also contains regular text or paragraphs outside the diagram, generate additional cards for that content too.

SELF-CHECK: before returning JSON, read each card and ask:
1. "Would a smart 16-year-old understand this immediately?" If not, rewrite it.
2. For diagram cards: "Does the front make sense if the reader has NEVER seen the diagram?" If the front mentions the chart, graph, figure, or diagram in any way (other than the "(Diagram)" tag), rewrite it as a standalone factual question.
3. For diagram cards: "Does the back reference any visual elements (symbols, colors, markers, axis labels)?" If so, rewrite using only words — no "marked ×", "circles", "blue line", etc.

Return ONLY valid JSON in this exact format, no other text:
{
  "cards": [
    {
      "front": "question text",
      "back": "answer text",
      "tags": ["tag1", "tag2"],
      "is_image_card": false
    }
  ]
}

Tags should reflect the topic (e.g. "anatomy", "biochemistry", "chapter-3").
For image cards set is_image_card to true."""


def encode_image(image_path: str) -> str:
    """Return base64 string of image, resizing if needed to stay under API limit."""
    with open(image_path, "rb") as f:
        data = f.read()
    if len(base64.standard_b64encode(data)) <= MAX_IMAGE_BYTES:
        return base64.standard_b64encode(data).decode("utf-8")
    # Resize down until it fits
    img = Image.open(io.BytesIO(data))
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
    while True:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        if len(base64.standard_b64encode(data)) <= MAX_IMAGE_BYTES:
            break
        w, h = img.size
        img = img.resize((int(w * 0.8), int(h * 0.8)), Image.LANCZOS)
    return base64.standard_b64encode(data).decode("utf-8")


def _format_deck_context(cards: list[dict]) -> str:
    """Format existing deck cards into a prompt section."""
    if not cards:
        return ""
    lines = ["EXISTING CARDS IN THIS DECK (use as context — do NOT duplicate these):"]
    for i, c in enumerate(cards, 1):
        tags = ", ".join(c.get("tags", []))
        line = f'{i}. Q: "{c["front"]}" / A: "{c["back"]}"'
        if tags:
            line += f"  [{tags}]"
        lines.append(line)
    lines.append("")
    lines.append("Use these existing cards to:")
    lines.append("- NEVER create a card that tests the same fact as an existing one, even if worded differently.")
    lines.append("- Match the style, difficulty level, and tone of the existing cards.")
    lines.append("- Assume the student already knows concepts covered by existing cards — build on that knowledge rather than re-explaining basics.")
    lines.append("- Use the same tag conventions as existing cards.\n")
    return "\n".join(lines)


def _build_prompt(config: dict) -> str:
    prompt = PROMPT_TEMPLATE

    # Add deck context before RULES if available
    deck_context = _format_deck_context(config.get("deck_context", []))
    if deck_context:
        prompt = prompt.replace("RULES:", deck_context + "RULES:", 1)

    # Add transcript context if available (YouTube video mode)
    transcript = config.get("transcript_context", "").strip()
    if transcript:
        timestamp = config.get("timestamp")
        video_title = config.get("video_title", "")
        ts_str = ""
        if timestamp is not None:
            total = int(timestamp)
            m, s = divmod(total, 60)
            h, m = divmod(m, 60)
            ts_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        header = "TRANSCRIPT CONTEXT"
        if ts_str:
            header += f" (around timestamp {ts_str})"
        if video_title:
            header += f" from \"{video_title}\""
        header += ":\n"
        transcript_block = (
            f"{header}{transcript}\n\n"
            f"Use this transcript alongside the screenshot to generate accurate cards. "
            f"The transcript provides spoken context that may clarify or supplement what's visible in the screenshot.\n\n"
        )
        prompt = prompt.replace("RULES:", transcript_block + "RULES:", 1)

    custom = config.get("custom_prompt", "").strip()
    if not custom:
        return prompt
    # Place the user instruction at the top (before RULES) for maximum weight,
    # and reinforce it in the SELF-CHECK so the model verifies compliance.
    header = (
        f"IMPORTANT — USER INSTRUCTION (this overrides any conflicting rules below):\n"
        f"{custom}\n"
        f"If this instruction specifies a style, tone, or format, use it even if it "
        f"conflicts with the default rules (e.g. if the user says to rhyme, write "
        f"rhyming cards even though the default rules say 'plain english').\n\n"
    )
    check_extra = f" Also verify each card follows the user instruction: \"{custom}\""
    prompt = prompt.replace("RULES:", header + "RULES:", 1)
    prompt = prompt.replace(
        "Would a smart 16-year-old understand this immediately?",
        "Would a smart 16-year-old understand this immediately?" + check_extra,
    )
    return prompt


def _parse_cards(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract the first JSON object from the response
        data = _extract_json(raw)
        if data is None:
            preview = raw[:200]
            raise ValueError(f"Model returned invalid JSON. Response: {preview}...")
    return data.get("cards", [])


def _extract_json(text: str) -> dict | None:
    """Try to find and parse a JSON object embedded in free text."""
    # Find the outermost { ... } in the response
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def generate_cards(image_path: str, config: dict) -> list[dict]:
    provider = config.get("model", {}).get("provider", "anthropic")
    if provider == "anthropic":
        return _generate_anthropic(image_path, config)
    else:
        return _generate_openai_compat(image_path, config)


def _generate_anthropic(image_path: str, config: dict) -> list[dict]:
    import anthropic

    api_key    = config["api_keys"].get("anthropic", "")
    if not api_key:
        raise ValueError("No Anthropic API key set — open localhost:5789 and add your key.")
    model_name = config["model"].get("model_name", "claude-sonnet-4-6")
    prompt     = _build_prompt(config)
    b64        = encode_image(image_path)

    client  = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model_name,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text",  "text": prompt},
            ],
        }],
    )
    return _parse_cards(message.content[0].text)


def _generate_openai_compat(image_path: str, config: dict) -> list[dict]:
    from openai import OpenAI

    model_cfg  = config["model"]
    provider   = model_cfg["provider"]
    model_name = model_cfg.get("model_name", "gpt-4o")
    prompt     = _build_prompt(config)
    b64        = encode_image(image_path)

    if provider == "openai":
        base_url = None
        api_key  = config["api_keys"].get("openai", "")
        if not api_key:
            raise ValueError("No OpenAI API key set — open localhost:5789 and add your key.")
    elif provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        api_key  = config["api_keys"].get("groq", "")
        if not api_key:
            raise ValueError("No Groq API key set — open localhost:5789 and add your key.")
    elif provider == "gemini":
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        api_key  = config["api_keys"].get("gemini", "")
        if not api_key:
            raise ValueError("No Gemini API key set — open localhost:5789 and add your key.")
    else:  # custom
        base_url = model_cfg.get("base_url") or "http://localhost:11434/v1"
        api_key  = "not-needed"

    client_kwargs: dict = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client   = OpenAI(**client_kwargs)
    create_kwargs: dict = {
        "model": model_name,
        "max_tokens": 4096,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text",      "text": prompt},
            ],
        }],
    }
    # Force JSON output where supported (Ollama, LM Studio, vLLM, OpenAI)
    if provider in ("custom", "openai"):
        create_kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**create_kwargs)
    return _parse_cards(response.choices[0].message.content)
