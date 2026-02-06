import frappe
from frappe import _

@frappe.whitelist()
def save_cv_to_pdf_upload(file_url, job_id, designation, action):
    if not file_url or not job_id:
        frappe.throw(_("File or Job Opening ID is missing."))

    pdf_upload_name = frappe.db.get_value("PDF Upload", {"job_title": job_id}, "name")

    if pdf_upload_name:
        doc = frappe.get_doc("PDF Upload", pdf_upload_name)
    else:
        # Agar nahi hai toh naya record banayein
        doc = frappe.new_doc("PDF Upload")
        # Job Opening ki 'name' field -> PDF Upload ki 'job_title' field mein
        doc.job_title = job_id
        # Job Opening ki 'designation' field -> PDF Upload ki 'designation' field mein
        doc.designation = designation

    # 2. Child table 'files' mein entry add karein
    doc.append("files", {
        "file_upload": file_url
    })

    # 3. Save aur Commit
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    # Action specific processing yahan trigger karein
    if action == "Parse":
        # parse_cv(file_url)
        pass
    elif action == "Score":
        # score_cv(file_url)
        pass

    return doc.name