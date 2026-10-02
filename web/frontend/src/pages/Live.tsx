import { useEffect, useState } from "react";
import { api, type RunEvent } from "../api";
import { Bar } from "../ui";

// Campaign view: replays the stored event log and, if the campaign is still
// running, follows it live over a WebSocket.
export function LivePage({ runId }: { runId: string }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let ws: WebSocket | undefined;
    let cancelled = false;
    api.events(runId).then((initial) => {
      if (cancelled) return;
      setEvents(initial);
      if (!initial.some((e) => e.type === "campaign.finished")) {
        ws = api.eventsSocket(runId);
        setLive(true);
        const seen = initial.length;
        let count = 0;
        ws.onmessage = (msg) => {
          count += 1;
          if (count <= seen) return; // the socket replays from the start of the file
          setEvents((prev) => [...prev, JSON.parse(msg.data as string) as RunEvent]);
        };
        ws.onclose = () => setLive(false);
      }
    });
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [runId]);

  const started = events.find((e) => e.type === "campaign.started");
  const total = Number(started?.data.tests ?? 0) + events.filter((e) => e.type === "generation.finished").reduce((a, e) => a + Number(e.data.tests ?? 0), 0);
  const finished = events.filter((e) => e.type === "case.finished");
  const count = (v: string) => finished.filter((e) => e.data.verdict === v).length;
  const skipped = events.filter((e) => e.type === "case.skipped").length;
  const modelCalls = events.filter((e) => e.type === "model.call");
  const retries = events.filter((e) => e.type === "retry").length;
  const notable = events.filter((e) => ["budget.exhausted", "early_stop", "error", "retry", "generation.finished", "campaign.finished"].includes(e.type));

  return (
    <>
      <p>
        {live ? <span className="verdict uncertain">running</span> : <span className="verdict pass">finished</span>}{" "}
        {finished.length + skipped} / {total || "?"} tests
      </p>
      <Bar
        parts={[
          { value: count("pass"), tone: "good", label: "pass" },
          { value: count("fail"), tone: "bad", label: "fail" },
          { value: count("uncertain"), tone: "warn", label: "uncertain" },
          { value: skipped, tone: "idle", label: "skipped" },
          { value: Math.max(0, total - finished.length - skipped), tone: "pending", label: "pending" },
        ]}
      />
      <table>
        <tbody>
          <tr>
            <td>pass / fail / uncertain / error</td>
            <td>
              {count("pass")} / {count("fail")} / {count("uncertain")} / {count("error")}
            </td>
          </tr>
          <tr>
            <td>Target calls / retries</td>
            <td>
              {events.filter((e) => e.type === "target.call").length} / {retries}
            </td>
          </tr>
          <tr>
            <td>Model calls (judge / generator)</td>
            <td>
              {modelCalls.filter((e) => e.data.role === "judge").length} / {modelCalls.filter((e) => e.data.role === "generator").length}
            </td>
          </tr>
        </tbody>
      </table>
      <h2>Event log</h2>
      <table>
        <tbody>
          {notable.map((e, i) => (
            <tr key={i}>
              <td className="small">{new Date(e.ts).toLocaleTimeString()}</td>
              <td>
                <code>{e.type}</code>
              </td>
              <td className="small">{JSON.stringify(e.data)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
