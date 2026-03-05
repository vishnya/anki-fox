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
- Back: 1–2 sentences max, plain english. Use jargon only when the jargon itself is what's being learned. Never use phrases like "as illustrated", "in the context of", or "with respect to".
- If you are tempted to write a back longer than 2 sentences, stop — split it into multiple cards instead.
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
- Generate one card with is_image_card: true for the diagram itself
- Front: a specific conceptual question about what the diagram illustrates — not generic like "What does this diagram show?" but precise enough that someone could answer it cold, e.g. "What is the input/output flow of a multimodal model?" or "How does CLIP training work?"
- Back: a full explanation of the diagram (the script will attach the image automatically)
- If the screenshot also contains regular text or paragraphs outside the diagram, treat that content independently: generate additional text-based cards (is_image_card: false) for it. Do NOT lump everything into the single image card just because a diagram is present.

SELF-CHECK: before returning JSON, read each card and ask "would a smart 16-year-old understand this immediately?" If not, rewrite it until they would.

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


def _build_prompt(config: dict) -> str:
    custom = config.get("custom_prompt", "").strip()
    if not custom:
        return PROMPT_TEMPLATE
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
    prompt = PROMPT_TEMPLATE.replace("RULES:", header + "RULES:", 1)
    prompt = prompt.replace(
        "would a smart 16-year-old understand this immediately?",
        "would a smart 16-year-old understand this immediately?" + check_extra,
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
        max_tokens=2000,
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
        "max_tokens": 2000,
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
