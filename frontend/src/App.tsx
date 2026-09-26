import { motion } from "framer-motion";
import { Lock } from "lucide-react";
import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { EmptyState, Skeleton } from "./components/ui";
import { AuthProvider, useAuth, type Capability } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";

const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const NewRequest = lazy(() => import("./pages/NewRequest"));
const Requests = lazy(() => import("./pages/Requests"));
const CaseDetail = lazy(() => import("./pages/CaseDetail"));
const Inbox = lazy(() => import("./pages/Inbox"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Timetable = lazy(() => import("./pages/Timetable"));
const Fairness = lazy(() => import("./pages/Fairness"));
const Graph = lazy(() => import("./pages/Graph"));
const Policy = lazy(() => import("./pages/Policy"));
const Transparency = lazy(() => import("./pages/Transparency"));
const Observability = lazy(() => import("./pages/Observability"));
const Experiments = lazy(() => import("./pages/Experiments"));

function Splash() {
  return (
    <div className="grid h-full place-items-center">
      <motion.div
        animate={{ scale: [1, 1.08, 1], rotate: [0, 6, 0] }}
        transition={{ duration: 1.6, repeat: Infinity }}
        className="grid size-14 place-items-center rounded-2xl grad-bg shadow-xl shadow-brand/30"
      >
        <svg viewBox="0 0 32 32" className="size-7">
          <path d="M7 22l6-12 5 8 2.5-3.5L25 22" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </motion.div>
    </div>
  );
}

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-28" />
      <Skeleton className="h-80" />
    </div>
  );
}

function Guard({ need, children }: { need?: Capability; children: ReactNode }) {
  const { can } = useAuth();
  if (need && !can(need)) return <EmptyState icon={Lock} title="Not available for your role" text="The server enforces this too; the page is hidden to keep things simple." />;
  return <>{children}</>;
}

function Routed() {
  const { user, ready } = useAuth();
  if (!ready) return <Splash />;
  if (!user)
    return (
      <Suspense fallback={<Splash />}>
        <Login />
      </Suspense>
    );
  return (
    <Shell>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<Guard need="request"><NewRequest /></Guard>} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/requests/:id" element={<CaseDetail />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/approvals" element={<Guard need="approve"><Approvals /></Guard>} />
          <Route path="/timetable" element={<Timetable />} />
          <Route path="/fairness" element={<Fairness />} />
          <Route path="/policy" element={<Policy />} />
          <Route path="/transparency" element={<Transparency />} />
          <Route path="/graph" element={<Guard need="observe"><Graph /></Guard>} />
          <Route path="/observability" element={<Guard need="observe"><Observability /></Guard>} />
          <Route path="/experiments" element={<Guard need="observe"><Experiments /></Guard>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routed />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
