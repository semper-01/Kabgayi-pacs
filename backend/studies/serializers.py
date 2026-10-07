"""Projection helpers that map raw Orthanc resources to clean API responses.

No models are involved: studies are represented purely from the Orthanc REST
API response, keeping Django free of any DICOM database duplication.
"""


def serialize_study(study_resource, modalities=None):
    """Build the clean study representation exposed by the API.

    ``study_resource`` is the JSON returned by Orthanc (an expanded study
    resource). ``modalities`` is an optional iterable of modality tags derived
    from the study's series (Modality is a series-level DICOM tag). Missing or
    empty values are mapped to empty strings; we never invent metadata that
    Orthanc does not provide.
    """
    main_tags = study_resource.get("MainDicomTags", {}) or {}
    patient_tags = study_resource.get("PatientMainDicomTags", {}) or {}
    modality_value = ""
    if modalities:
        modality_value = ", ".join(sorted(str(m) for m in modalities if m))
    return {
        "study_id": study_resource.get("ID", ""),
        "patient_name": patient_tags.get("PatientName", ""),
        "patient_id": patient_tags.get("PatientID", ""),
        "study_instance_uid": main_tags.get("StudyInstanceUID", ""),
        "accession_number": main_tags.get("AccessionNumber", ""),
        "study_date": main_tags.get("StudyDate", ""),
        "modality": modality_value,
        "study_description": main_tags.get("StudyDescription", ""),
    }