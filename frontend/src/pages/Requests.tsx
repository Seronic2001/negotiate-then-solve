import clsx from "clsx";
import { ChevronRight, ListChecks, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Avatar, Badge, Card, EmptyState, PageHeader, Skeleton, StatusBadge, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago, STATUS } from "../lib/meta";
import type { Status } from "../lib/types";

type Filter = "all" | "active" | "done" | "exits";
const ACTIVE: Status[] = ["received", "classified", "policy_checked", "compiled", "solved", "negotiating", "fairness_audited", "awaiting_approval"];
const EXITS: Status[] = ["refused", "denied", "clarification_requested", "escalated", "forwarded"];

export default function Requests() {
  const { can } = useAuth();
  const [scope, setScope] = useState<"mine" | "all">(can("see_all") ? "all" : "mine");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const { data, loading } = useApi(() => api.cases(scope), [scope], 3000);

  const rows = useMemo(() => {
    const ql = q.toLowerCase();
    return (data ?? []).filter((c) => {
      if (filter === "active" && !ACTIVE.includes(c.status)) return false;
      if (filter === "done" && !["published", "answered"].includes(c.status)) return false;
      if (filter === "exits" && !EXITS.includes(c.status)) return false;
      return !ql || `${c.id} ${c.text} ${c.sender_name}`.toLowerCase().includes(ql);
    });
  }, [data, filter, q]);

  const count = (f: Filter) =>
    (data ?? []).filter((c) =>
      f === "all" ? true : f === "active" ? ACTIVE.includes(c.status) : f === "done" ? ["published", "answered"].includes(c.status) : EXITS.includes(c.status),
    ).length;

  return (
    <>
      <PageHeader
        title={scope === "all" ? "All requests" : "Your requests"}
        subtitle="Open a request to see how it was handled, step by step."
        actions={
          can("see_all") && (
            <Tabs
              tabs={[
                { id: "all", label: "Everyone" },
                { id: "mine", label: "Mine" },
              ]}
              value={scope}
              onChange={setScope}
            />
          )
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <Tabs
            tabs={[
              { id: "all", label: "All", count: count("all") },
              { id: "active", label: "In progress", count: count("active") },
              { id: "done", label: "Done", count: count("done") },
              { id: "exits", label: "Stopped", count: count("exits") },
            ]}
            value={filter}
            onChange={setFilter}
          />
          <div className="relative ml-auto w-full max-w-xs">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter"
              className="h-8 w-full rounded-md border border-line bg-panel pl-8 pr-3 text-[13px] outline-none focus:border-brand/50"
            />
          </div>
        </div>
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : rows.length ? (
          <ul className="divide-y divide-line">
            {rows.map((c) => (
              <li key={c.id}>
                <Link to={`/requests/${c.id}`} className="group flex items-center gap-3.5 px-5 py-3 hover:bg-panel-2/60">
                  <Avatar name={c.sender_name} id={c.sender} size={30} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px]">{c.text}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink-3">
                      <span>{c.sender_name}</span>
                      <span>·</span>
                      <span>{ago(c.received_at)}</span>
                      {c.type && (
                        <>
                          <span>·</span>
                          <span>{c.type.replace("_", " ")}</span>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="hidden items-center gap-2 sm:flex">
                    {c.rounds > 0 && <Badge tone="warn">{c.rounds} round{c.rounds > 1 ? "s" : ""}</Badge>}
                  </div>
                  <StatusBadge status={c.status} live={c.running} />
                  <ChevronRight size={16} className={clsx("text-ink-3 transition-transform group-hover:translate-x-0.5", STATUS[c.status]?.terminal && "opacity-60")} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={ListChecks} title="No requests here" text="Requests you send appear here with their full audit trail." />
        )}
      </Card>
    </>
  );
}
