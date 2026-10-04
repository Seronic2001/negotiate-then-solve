import { ExternalLink } from "lucide-react";
import { StudyAdmin } from "../components/StudyAdmin";
import { Button, PageHeader } from "../components/ui";

/** The timetable office's page for the human study: codes, progress, agreement and export. */
export default function HumanStudy() {
  return (
    <>
      <PageHeader
        title="Human study"
        subtitle="Judge validation by the team and the anonymised faculty pilot. Issue codes here; participants answer on the study page."
        actions={
          <a href="/study" target="_blank" rel="noreferrer">
            <Button icon={ExternalLink}>Open the participant page</Button>
          </a>
        }
      />
      <StudyAdmin />
    </>
  );
}
