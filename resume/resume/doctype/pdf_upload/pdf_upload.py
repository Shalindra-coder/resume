

import frappe
import os
import json
import mimetypes
from pdfminer.high_level import extract_text
from frappe.model.document import Document
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import docx  # For .docx files
import google.generativeai as genai

class PDFUpload(Document):
    pass

@frappe.whitelist()
def process_pdfs(docname):
    """Enqueues the processing job for all types of files."""
    frappe.enqueue("resume.resume.doctype.pdf_upload.pdf_upload.process_files_background", queue="long", docname=docname)
    frappe.msgprint("File processing has been queued in the background.")

# --- AI Logic (UNCHANGED as per request) ---
@frappe.whitelist()
def list_available_gemini_models():
    """List available Gemini models for debugging."""
    try:
        api_key = frappe.conf.get("gemini_api_key")
        if not api_key:
            return {"error": "Gemini API key missing in site_config.json"}
        
        genai.configure(api_key=api_key)
        models = genai.list_models()
        available_models = []
        model_details = []
        for model in models:
            if 'generateContent' in model.supported_generation_methods:
                model_name = model.name
                model_id = model_name.replace('models/', '')
                available_models.append(model_id)
                model_details.append({
                    "full_name": model_name,
                    "model_id": model_id,
                    "display_name": getattr(model, 'display_name', 'N/A'),
                    "supported_methods": list(model.supported_generation_methods)
                })
        
        frappe.logger().info(f"Available Gemini models: {available_models}")
        return {"available_models": available_models, "model_details": model_details}
    except Exception as e:
        frappe.logger().error(f"Error listing Gemini models: {str(e)}")
        return {"error": str(e)}

def parse_with_gemini(text, job_title=None, job_description=None):
    """AI Logic: Send resume text to Gemini model and return structured JSON."""
    # (No changes made to this function as requested)
    try:
        api_key = frappe.conf.get("gemini_api_key")
        if not api_key:
            raise Exception("Gemini API key missing in site_config.json")

        genai.configure(api_key=api_key)
        prompt_path = frappe.get_app_path("resume", "resume", "doctype", "pdf_upload", "resume_prompt.txt")
        with open(prompt_path, "r") as f:
            prompt_template = f.read()

        prompt = prompt_template.replace("{{RESUME_TEXT}}", text)
        prompt = prompt.replace("{{JOB_TITLE}}", job_title or "N/A")
        prompt = prompt.replace("{{JOB_DESCRIPTION}}", job_description or "N/A")

        model_names = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
        last_error = None
        skipped_models = []
        
        def try_models(models_to_try):
            nonlocal last_error
            for model_name in models_to_try:
                try:
                    frappe.logger().info(f"Attempting Gemini model: {model_name}")
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    cleaned = response.text.strip()
                    if cleaned.startswith("```json"): cleaned = cleaned[7:]
                    if cleaned.endswith("```"): cleaned = cleaned[:-3]
                    return json.loads(cleaned.strip())
                except Exception as e:
                    if "Computer Use tool" in str(e):
                        skipped_models.append(model_name)
                        continue
                    last_error = e
                    continue
            return None

        result = try_models(model_names)
        if result: return result
        
        # Dynamic fallback
        models = genai.list_models()
        dynamic_models = [m.name.replace('models/', '') for m in models 
                          if 'generateContent' in m.supported_generation_methods 
                          and m.name.replace('models/', '') not in model_names]
        return try_models(dynamic_models) or (lambda: exec('raise last_error'))()
    except Exception as e:
        frappe.logger().error(f"Gemini parsing failed: {e}")
        raise

# --- Text Extraction Logic (Enhanced for all formats) ---

def extract_text_from_any_file(file_path):
    """Detects file type and extracts text accordingly."""
    ext = os.path.splitext(file_path)[1].lower()
    text = ""

    frappe.logger().info(f"Starting extraction for file: {file_path} with extension: {ext}")

    if ext == ".pdf":
        text = extract_text(file_path)
        if not text.strip():
            frappe.logger().info(f"PDF looks like an image, starting OCR: {file_path}")
            text = extract_text_with_ocr(file_path)
    
    elif ext == ".docx":
        doc = docx.Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
    
    elif ext in [".jpg", ".jpeg", ".png"]:
        text = pytesseract.image_to_string(Image.open(file_path))
    
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    
    else:
        frappe.logger().warning(f"Unsupported file format: {ext}")
        return None

    return text.strip()

def extract_text_with_ocr(file_path):
    """OCR for Scanned PDFs."""
    try:
        images = convert_from_path(file_path)
        return "\n".join([pytesseract.image_to_string(img) for img in images])
    except Exception as e:
        frappe.logger().error(f"OCR Error: {str(e)}")
        return ""

# --- Background Job (Enhanced Logging) ---

def process_files_background(docname):
    """Processes any uploaded file, extracts text, and creates Applicants."""
    try:
        doc = frappe.get_doc("PDF Upload", docname)
        if not doc.get("files"):
            frappe.logger().warning(f"PDF Upload {docname}: No files found.")
            return

        for file_entry in doc.get("files"):
            file_url = file_entry.get("file_upload")
            if not file_url: continue
            
            # File Path logic
            if file_url.startswith("/private/files/"):
                file_path = frappe.get_site_path(file_url.lstrip("/"))
            else:
                file_path = frappe.get_site_path("public" + file_url)

            if not os.path.exists(file_path):
                frappe.logger().error(f"File not found on server: {file_path}")
                continue

            # 1. Extract Text
            try:
                text = extract_text_from_any_file(file_path)
                if not text:
                    frappe.logger().error(f"Could not extract any text from {file_url}")
                    continue
            except Exception as e:
                frappe.logger().error(f"Extraction error for {file_url}: {str(e)}")
                continue

            # 2. Parse with AI
            try:
                job_desc = frappe.db.get_value("Job Opening", doc.job_title, "description") if doc.job_title else None
                applicant_data = parse_with_gemini(text, doc.job_title, job_desc)
            except Exception as e:
                 frappe.logger().error(f"AI Parsing failed for {file_url}: {str(e)}")
                 continue
            
            # 3. Validation & Creation
            email = applicant_data.get("email_id")
            if not email or not applicant_data.get("applicant_name"):
                frappe.logger().warning(f"Missing Name/Email in AI response for {file_url}")
                continue

            if frappe.db.exists("Job Applicant", {"email_id": email}):
                frappe.logger().info(f"Skipping: Applicant {email} already exists.")
                continue

            try:
                new_applicant = frappe.get_doc({
                    "doctype": "Job Applicant",
                    "applicant_name": applicant_data.get("applicant_name"),
                    "email_id": email,
                    "phone_number": applicant_data.get("phone_number"),
                    "resume_attachment": file_url,
                    "status": "Open",
                    "job_title": doc.job_title,
                    "designation": doc.designation,
                    "applicant_rating": applicant_data.get("applicant_rating"),
                    "score": applicant_data.get('score'),
                    "fit_level": applicant_data.get('fit_level'),
                    "justification_by_ai": applicant_data.get('justification_by_ai')
                })
                new_applicant.insert(ignore_permissions=True)
                frappe.logger().info(f"Successfully Created Applicant: {new_applicant.name} from {file_url}")
            except Exception as e:
                frappe.logger().error(f"Database insertion failed for {email}: {str(e)}")

    except Exception as e:
        frappe.logger().error(f"Critical error in background job {docname}: {str(e)}")