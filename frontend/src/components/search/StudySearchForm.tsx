import { useState, type FormEvent } from "react";
import { EMPTY_FILTERS, type StudyFilters } from "../../types/study";

interface StudySearchFormProps {
  onSearch: (filters: StudyFilters) => void;
  busy: boolean;
}

export function StudySearchForm({ onSearch, busy }: StudySearchFormProps) {
  const [filters, setFilters] = useState<StudyFilters>({ ...EMPTY_FILTERS });

  function update(field: keyof StudyFilters, value: string) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(filters);
  }

  function clear() {
    const cleared = { ...EMPTY_FILTERS };
    setFilters(cleared);
    onSearch(cleared);
  }

  return (
    <form className="search-panel" onSubmit={submit}>
      <div className="search-grid">
        <label className="field">
          <span>Patient name</span>
          <input
            value={filters.patient_name}
            onChange={(event) => update("patient_name", event.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Patient ID</span>
          <input
            value={filters.patient_id}
            onChange={(event) => update("patient_id", event.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Accession number</span>
          <input
            value={filters.accession_number}
            onChange={(event) => update("accession_number", event.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Study date</span>
          <input
            type="date"
            value={filters.study_date}
            onChange={(event) => update("study_date", event.target.value)}
          />
        </label>
        <label className="field">
          <span>Modality</span>
          <input
            value={filters.modality}
            onChange={(event) => update("modality", event.target.value)}
            placeholder="e.g. CT"
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>Study description</span>
          <input
            value={filters.study_description}
            onChange={(event) => update("study_description", event.target.value)}
            autoComplete="off"
          />
        </label>
      </div>
      <div className="search-actions">
        <button className="button button-primary" type="submit" disabled={busy}>
          Search studies
        </button>
        <button className="button button-secondary" type="button" onClick={clear} disabled={busy}>
          Clear filters
        </button>
      </div>
    </form>
  );
}
