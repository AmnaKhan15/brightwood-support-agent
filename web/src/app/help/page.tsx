"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useApp } from "@/components/providers";
import { Button, Card, Eyebrow, Note, ScoreBar } from "@/components/ui";
import type { Article, SearchHit } from "@/lib/types";

export default function Help() {
  const { api } = useApp();
  const [draft, setDraft] = useState("Can I return a clearance item?");
  const [query, setQuery] = useState(draft);
  const search = useQuery({
    queryKey: ["search", query],
    queryFn: () => api<{ query: string; mode: string; hits: SearchHit[] }>(`/api/help/search?q=${encodeURIComponent(query)}`),
    enabled: !!query.trim(),
  });
  const articles = useQuery({ queryKey: ["articles"], queryFn: () => api<Article[]>("/api/help/articles"), staleTime: Infinity });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft);
  };

  return (
    <section className="flex flex-col gap-6">
      <div>
        <Eyebrow>Help centre</Eyebrow>
        <h1 className="mt-1 text-3xl font-bold">Search the articles</h1>
      </div>
      <Card className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex gap-2">
          <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Your question" maxLength={200}
            className="min-w-0 flex-1 rounded-xl border border-line bg-bg px-3 py-2.5" />
          <Button type="submit" variant="solid">Search</Button>
        </form>
        <p className="text-sm text-muted">
          This is the same search the assistants run{search.data ? ` (${search.data.mode})` : ""}. Each piece of an article is stored with a word
          vector and, when an embedding model is configured, a meaning vector in pgvector. Your question is compared with both; the closest pieces win.
        </p>
        {search.error && <Note tone="bad">{(search.error as Error).message}</Note>}
        <div className="flex flex-col gap-2.5">
          {search.data?.hits.map((h, n) => (
            <div key={h.id} className="rounded-xl border border-line p-3">
              <div className="mb-1 flex justify-between font-mono text-xs"><span className="text-brand">{n + 1}. {h.id}</span><span>{h.score.toFixed(2)}</span></div>
              <ScoreBar score={h.score} />
              <p className="mt-2 text-sm">{h.text}</p>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <Eyebrow>The library</Eyebrow>
        <h2 className="mb-3 mt-1 text-xl font-bold">
          {articles.data ? `${articles.data.length} articles, ${articles.data.reduce((n, a) => n + a.chunks.length, 0)} pieces` : "Loading…"}
        </h2>
        <div className="flex flex-col divide-y divide-line">
          {articles.data?.map((a) => (
            <details key={a.doc} className="py-2">
              <summary className="cursor-pointer font-semibold capitalize">{a.doc.replace(/_/g, " ")} <span className="text-xs text-muted">({a.chunks.length})</span></summary>
              <div className="mt-2 flex flex-col gap-3">
                {a.chunks.map((c) => (
                  <p key={c.id} className="text-sm"><span className="font-mono text-xs text-brand">{c.id}</span><br />{c.text}</p>
                ))}
              </div>
            </details>
          ))}
        </div>
      </Card>
    </section>
  );
}
