import { useState } from "react";
import { admin, type ChallengeCatalogItem } from "../../api";
import { usePoll } from "../../hooks";

export default function Challenges() {
  const [showPatches, setShowPatches] = useState(false);
  const { data, error, loading } = usePoll(
    () => admin.challenges({ include_patches: showPatches }),
    10000,
    [showPatches],
  );

  if (error) return <div className="msg error">{error}</div>;
  if (!data && loading) return <div className="msg">Loading challenges...</div>;
  if (!data) return <div className="msg">No challenge catalog available.</div>;

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Challenge Catalog</h1>
          <p className="subtitle">
            {data.challenges.length} services from <code>platform/challenges</code>
          </p>
        </div>
        <div className="actions-row">
          <button
            className={`btn ${showPatches ? "btn-warning" : "btn-ghost"}`}
            onClick={() => setShowPatches((v) => !v)}
            disabled={!data.can_reveal_patches}
            title={data.can_reveal_patches ? "Toggle patch notes" : "Patch notes unlock after the game stops"}
          >
            {showPatches ? "Hide patch notes" : "Reveal patch notes"}
          </button>
        </div>
      </header>

      {!data.can_reveal_patches && (
        <div className="alert alert-info">
          Patch notes are hidden while the game is running. Stop the game to reveal organizer patch guidance.
        </div>
      )}

      <div className="challenge-grid">
        {data.challenges.map((challenge) => (
          <ChallengeCard
            key={`${challenge.slot}-${challenge.name}`}
            challenge={challenge}
            patchesRevealed={data.patches_revealed}
          />
        ))}
      </div>
    </>
  );
}

function ChallengeCard({
  challenge,
  patchesRevealed,
}: {
  challenge: ChallengeCatalogItem;
  patchesRevealed: boolean;
}) {
  return (
    <article className="card challenge-card">
      <div className="challenge-title">
        <div>
          <span className="challenge-slot">{challenge.slot || challenge.path}</span>
          <h2>{titleCase(challenge.name)}</h2>
        </div>
        <span className="badge badge-neutral">{challenge.difficulty}</span>
      </div>

      <div className="challenge-meta">
        <span>{challenge.runtime}</span>
        <span>{challenge.flagstores} flagstores</span>
        <span>{challenge.vulnerabilities} vulns</span>
        <span>{challenge.rabbit_holes} rabbit holes</span>
      </div>

      <div className="tag-row">
        {challenge.categories.map((category) => (
          <span className="tag" key={category}>
            {category}
          </span>
        ))}
      </div>

      <p className="challenge-summary">{summary(challenge.summary)}</p>

      {patchesRevealed && (
        <div className="patch-notes">
          <h3>Patch Notes</h3>
          <pre>{cleanPatchNotes(challenge.patch_notes) || "No patch notes found."}</pre>
        </div>
      )}
    </article>
  );
}

function summary(markdown: string): string {
  const lines = markdown
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  return lines.slice(0, 4).join(" ");
}

function cleanPatchNotes(markdown: string | null): string {
  if (!markdown) return "";
  return markdown
    .split("\n")
    .filter((line) => !line.trim().startsWith("#"))
    .join("\n")
    .trim();
}

function titleCase(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
