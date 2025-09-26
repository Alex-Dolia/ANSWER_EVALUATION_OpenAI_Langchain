from bs4 import BeautifulSoup
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
import re
import os
import json

# === Configuration ===
OPENAI_API_KEY = "PUT YOUR OPEN AI KEY HERE GO TO https://platform.openai.com/api-keys"

# === LangChain Model Initialization ===
llm = ChatOpenAI(
    model="gpt-4", 
    temperature=0,
    openai_api_key=OPENAI_API_KEY
)

def evaluate_student_answer(question, golden_reference, student_html_answer):
    """
    Evaluate a student's HTML answer against a golden reference.
    
    Args:
        question (str): The question being answered
        golden_reference (str): The correct answer in plain text
        student_html_answer (str): Student's answer in HTML format
    
    Returns:
        dict: Contains evaluation result, highlighted HTML, and extracted sentences
    """
    
    # === Step 1: Extract plain text from student HTML ===
    soup = BeautifulSoup(student_html_answer, "html.parser")
    student_plain_text = soup.get_text().strip()
    
    # === Step 2: Structured JSON prompt for evaluation (per-sentence labeling) ===
    evaluation_prompt = f"""
You are an expert educational evaluator. Analyze the student's answer against the golden reference.

Return ONLY valid JSON (no prose). Prefer this schema:
{{
  "sentences": [
    {{"full": string, "part": string, "label": "correct" | "incorrect"}}
  ]
}}

Legacy schema also accepted (for backward compatibility):
{{
  "Correct": [{{"part": string, "full": string}}],
  "incorrect": {{"part": string, "full": string}} | null
}}

Guidelines:
- Decide for EVERY sentence/phrase from the student's answer whether it is correct or incorrect.
- Use "full" for the entire sentence/phrase from the student's answer that you are judging.
- Use "part" as the minimal substring inside that sentence that specifically supports why it is correct or incorrect.
- Only the "part" will be colored in the HTML output; "full" determines the sentence-level decision.
- If a sentence has both correct and incorrect claims, split into multiple entries with the same "full" but different "part" and labels.

Question: {question}

Golden Reference: {golden_reference}

Student Answer (Plain Text): {student_plain_text}
"""

    # === Step 3: Run evaluation ===
    try:
        response = llm.invoke([HumanMessage(content=evaluation_prompt)])
        evaluation_result = response.content
    except Exception as e:
        print(f"Error during LLM evaluation: {e}")
        return None

    # === Step 4: Parse JSON result or fallback to regex extraction ===
    # We will highlight PARTS when available; otherwise fall back to full sentences.
    correct_sentences = []
    incorrect_sentences = []

    parsed = None
    try:
        parsed = json.loads(evaluation_result)
    except Exception:
        parsed = None

    if isinstance(parsed, dict) and ("sentences" in parsed or "Correct" in parsed):
        # Preferred per-sentence schema
        if isinstance(parsed.get("sentences"), list):
            for item in parsed["sentences"]:
                if not isinstance(item, dict):
                    continue
                label = (item.get("label") or "").strip().lower()
                part_value = item.get("part") or item.get("full")
                if isinstance(part_value, str):
                    part_value = part_value.strip()
                if not part_value:
                    continue
                if label == "incorrect":
                    incorrect_sentences.append(part_value)
                elif label == "correct":
                    correct_sentences.append(part_value)
        else:
            # Legacy schema: prefer highlighting the minimal "part"
            correct_entries = parsed.get("Correct") or []
            for entry in correct_entries:
                if isinstance(entry, dict):
                    part_or_full = entry.get("part") or entry.get("full")
                    if isinstance(part_or_full, str) and part_or_full.strip():
                        correct_sentences.append(part_or_full.strip())
            incorrect_entry = parsed.get("incorrect")
            if isinstance(incorrect_entry, dict):
                part_or_full_incorrect = incorrect_entry.get("part") or incorrect_entry.get("full")
                if isinstance(part_or_full_incorrect, str) and part_or_full_incorrect.strip():
                    incorrect_sentences.append(part_or_full_incorrect.strip())
    else:
        # Fallback to legacy regex parsing if JSON not returned
        correct_match = re.search(r'CORRECT SENTENCES:\s*(.*?)(?=INCORRECT SENTENCES:|$)', evaluation_result, re.DOTALL | re.IGNORECASE)
        if correct_match:
            correct_text = correct_match.group(1).strip()
            correct_sentences = [line.strip() for line in correct_text.split('\n') if line.strip()]
        incorrect_match = re.search(r'INCORRECT SENTENCES:\s*(.*?)(?=EXPLANATIONS:|$)', evaluation_result, re.DOTALL | re.IGNORECASE)
        if incorrect_match:
            incorrect_text = incorrect_match.group(1).strip()
            incorrect_sentences = [line.strip() for line in incorrect_text.split('\n') if line.strip()]
    
    # === Step 5: Enhanced HTML highlighting ===
    highlighted_html = highlight_sentences_in_html(student_html_answer, correct_sentences, incorrect_sentences)
    
    return {
        'evaluation_result': evaluation_result,
        'highlighted_html': highlighted_html,
        'correct_sentences': correct_sentences,
        'incorrect_sentences': incorrect_sentences,
        'student_plain_text': student_plain_text
    }

def highlight_sentences_in_html(html_content, correct_sentences, incorrect_sentences):
    """
    Highlight correct and incorrect sentences in HTML content.
    
    Args:
        html_content (str): Original HTML content
        correct_sentences (list): List of correct sentences
        incorrect_sentences (list): List of incorrect sentences
    
    Returns:
        str: HTML with highlighted sentences
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Get all text nodes
    text_nodes = []
    for element in soup.find_all(text=True):
        if element.parent.name not in ['script', 'style']:
            text_nodes.append(element)
    
    # Process each text node
    for text_node in text_nodes:
        print(f"!!!!!! >> {text_node}")
        original_text = text_node.string
        if not original_text or not original_text.strip():
            continue
            
        highlighted_text = original_text
        
        # First highlight incorrect parts in BOLD RED
        for part in sorted(incorrect_sentences, key=len, reverse=True):
            print(f"INCORRECT !!!!!!---!!!!!! >> {part}")
            if part and part in highlighted_text:
                highlighted_text = highlighted_text.replace(
                    part, 
                    f'<span style="color: red; font-weight: bold; background-color: #ffebee;">{part}</span>'
                )
        
        # Then highlight correct parts in BOLD BLUE
        for part in sorted(correct_sentences, key=len, reverse=True):
            print(f"CORRECT !!!!!!+++!!!!!! >> {part}")
            if part and part in highlighted_text:
                highlighted_text = highlighted_text.replace(
                    part, 
                    f'<span style="color: blue; font-weight: bold; background-color: #e3f2fd;">{part}</span>'
                )
        
        # Replace the text node with highlighted version
        if highlighted_text != original_text:
            new_soup = BeautifulSoup(highlighted_text, "html.parser")
            text_node.replace_with(new_soup)
    
    return str(soup)

def main(question, student_html_answer, golden_reference):
    """
    Main function to demonstrate the answer evaluation system.
    """

    # === Run Evaluation ===
    print("=== Running Answer Evaluation ===\n")
    
    result = evaluate_student_answer(question, golden_reference, student_html_answer)
    print("!!!!!!!!!!!! result: ")
    print(result)
    
    if result:
        print("=== Evaluation Result ===\n")
        print(result['evaluation_result'])
        
        print("\n=== Extracted Correct Sentences ===\n")
        for i, sentence in enumerate(result['correct_sentences'], 1):
            print(f"{i}. {sentence}")
        
        print("\n=== Extracted Incorrect Sentences ===\n")
        for i, sentence in enumerate(result['incorrect_sentences'], 1):
            print(f"{i}. {sentence}")
        
        print("\n=== Highlighted HTML Output ===\n")
        print(result['highlighted_html'])
        
        # Create annotated_answers directory if it doesn't exist
        os.makedirs('annotated_answers', exist_ok=True)
        
        # Save highlighted HTML to file in annotated_answers directory
        output_file = os.path.join('annotated_answers', 'student_answer.html')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result['highlighted_html'])
        print(f"\nHighlighted HTML saved to '{output_file}'")
        
    else:
        print("Evaluation failed. Please check your API key and try again.")

if __name__ == "__main__":
    # === Example Inputs ===
    file_path = "questions/question.txt"
    # Open and read the file into a question
    with open(file_path, "r", encoding="utf-8") as f:
         question = f.read()
    
    file_path = "student_answers/student_answer.html"
    # Open and read the file into a student_answer
    with open(file_path, "r", encoding="utf-8") as f:
         student_html_answer = f.read()
    
    file_path = "golden_references/golden_reference.txt"
    # Open and read the file into a golden_reference
    with open(file_path, "r", encoding="utf-8") as f:
         golden_reference = f.read()


    main(question, student_html_answer, golden_reference)
