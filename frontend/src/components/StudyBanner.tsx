import { FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { study, studyCode, studyTask, type StudySession } from "../lib/study";

/** A pilot participant in the portal: whose shoes they are in, what to do, and the way back. */
export function useStudySession(): StudySession | null {
  const { user } = useAuth();
  const [session, setSession] = useState<StudySession | null>(null);
  useEffect(() => {
    if (!studyCode()) return setSession(null);
    study.me().then(setSession, () => setSession(null));
  }, [user?.id]);
  return session && session.kind === "pilot" && session.consented && user?.id === session.persona ? session : null;
}

export function StudyBanner() {
  const session = useStudySession();
  const task = studyTask();
  if (!session) return null;
  return (
    <div className="mb-6 flex flex-wrap items-start gap-3 rounded-lg border border-brand/30 bg-brand/5 px-4 py-3 text-[13.5px]">
      <FlaskConical size={16} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <p>
          <span className="font-medium">Study session {session.code}</span>
          <span className="text-ink-3"> · you are {session.persona_name}</span>
        </p>
        {task && <p className="mt-0.5 text-ink-2">{task}</p>}
      </div>
      <Link to="/study" className="shrink-0 font-medium text-brand hover:underline">
        Study tasks
      </Link>
    </div>
  );
}
