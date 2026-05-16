import { useState, useMemo, useCallback } from 'react';
import {
  Box, Typography, Chip, IconButton, Collapse,
  Button, Tooltip, Snackbar,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import DataObjectRoundedIcon from '@mui/icons-material/DataObjectRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import CompareArrowsRoundedIcon from '@mui/icons-material/CompareArrowsRounded';
import TimerRoundedIcon from '@mui/icons-material/TimerRounded';
import { useNavigate } from 'react-router-dom';

/* ── Status config ──────────────────────────────────────── */
const STATUS = {
  Pass:  { color: '#059669', bg: '#ECFDF5', bgStrong: '#D1FAE5', icon: CheckCircleRoundedIcon, label: 'PASS' },
  Fail:  { color: '#DC2626', bg: '#FEF2F2', bgStrong: '#FEE2E2', icon: CancelRoundedIcon, label: 'FAIL' },
  Error: { color: '#D97706', bg: '#FFFBEB', bgStrong: '#FEF3C7', icon: ErrorOutlineRoundedIcon, label: 'ERROR' },
};

const fmtType = (t) => ({
  row_count: 'Row Count', metadata: 'Metadata', null_check: 'Nulls',
  data: 'Data Diff', duplicate: 'Duplicates', aggregate: 'Aggregates',
}[t] || t);

/* ── Quality Score Ring ─────────────────────────────────── */
function ScoreRing({ score, size = 56 }) {
  const r = (size / 2) - 5;
  const circ = 2 * Math.PI * r;
  return (
    <Box sx={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="5" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#fff" strokeWidth="5"
          strokeDasharray={(score / 100) * circ + ' ' + circ} strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.8s ease' }} />
      </svg>
      <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Typography sx={{ fontSize: size * 0.28, fontWeight: 800, color: '#fff', fontFamily: '"JetBrains Mono", monospace' }}>
          {score}
        </Typography>
      </Box>
    </Box>
  );
}

/* ── Stat Pill ──────────────────────────────────────────── */
function StatPill({ label, value, color = 'rgba(255,255,255,0.9)', bold }) {
  return (
    <Box sx={{ textAlign: 'center', px: 1.5 }}>
      <Typography sx={{ fontSize: '1.1rem', fontWeight: bold ? 900 : 700, color, lineHeight: 1 }}>{value}</Typography>
      <Typography sx={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.6)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', mt: 0.25 }}>{label}</Typography>
    </Box>
  );
}

/* ── Mini check chip inside a test case card ───────────────── */
function CheckChip({ check }) {
  const cfg = STATUS[check.status] || STATUS.Pass;
  const Icon = cfg.icon;
  return (
    <Box sx={{
      display: 'inline-flex', alignItems: 'center', gap: 0.5,
      px: 1, py: 0.3, borderRadius: '6px',
      bgcolor: cfg.bg, border: `1px solid ${cfg.color}20`,
    }}>
      <Icon sx={{ fontSize: 12, color: cfg.color }} />
      <Typography sx={{ fontSize: '0.68rem', fontWeight: 600, color: cfg.color }}>
        {fmtType(check.check_type)}
      </Typography>
    </Box>
  );
}

/* ── Metric row inside expanded check ───────────────────── */
const METRIC_LABELS = {
  src_row_count: 'Source rows', tgt_row_count: 'Target rows',
  row_count_diff: 'Difference', pct_diff: '% difference',
  mismatched_null_columns: 'Null mismatches', mismatched_columns: 'Type mismatches',
  src_column_count: 'Source columns', tgt_column_count: 'Target columns',
  match_pct: 'Match %', rows_only_in_source: 'Only in source', rows_only_in_target: 'Only in target',
  rows_with_diffs: 'Rows with diffs', cell_diffs_found: 'Cell diffs',
  comparison_mode: 'Comparison mode', join_keys_used: 'Join keys',
  duplicate_rows_src: 'Duplicates (src)', duplicate_rows_tgt: 'Duplicates (tgt)',
  strategy: 'Strategy', root_cause: 'Root cause',
  root_cause_severity: 'Severity', root_cause_message: 'Diagnosis',
};
const fmtMetric = (k) => METRIC_LABELS[k] || k.replace(/_/g, ' ');
const fmtVal = (v) => v === null || v === undefined ? '—' : typeof v === 'number' ? v.toLocaleString() : String(v);

/* ── Test Case Card (expandable) ───────────────────────────── */
function TestCaseCard({ pair, defaultOpen }) {
  const [expanded, setExpanded] = useState(defaultOpen);
  const cfg = STATUS[pair.status] || STATUS.Error;
  const Icon = cfg.icon;
  const result = pair.result;
  const checks = result?.checks || [];
  const summary = result?.summary || {};
  const srcShort = pair.source_label.length > 60 ? '…' + pair.source_label.slice(-55) : pair.source_label;
  const tgtShort = pair.target_label.length > 60 ? '…' + pair.target_label.slice(-55) : pair.target_label;

  return (
    <Box sx={{
      bgcolor: '#fff', borderRadius: '12px',
      border: `1px solid ${pair.status === 'Pass' ? 'rgba(15,23,42,0.06)' : cfg.color + '25'}`,
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      overflow: 'hidden',
      transition: 'border-color 0.15s',
    }}>
      {/* Header — always visible */}
      <Box
        onClick={() => setExpanded(!expanded)}
        sx={{
          display: 'flex', alignItems: 'center', gap: 1.5,
          px: 2.5, py: 1.75, cursor: 'pointer',
          '&:hover': { bgcolor: '#FAFBFC' },
          transition: 'background 0.15s',
        }}
      >
        {/* Status indicator bar */}
        <Box sx={{ width: 4, height: 36, borderRadius: '2px', bgcolor: cfg.color, flexShrink: 0 }} />

        {/* Index */}
        <Typography sx={{
          fontSize: '0.72rem', fontWeight: 700, color: '#94A3B8',
          fontFamily: '"JetBrains Mono", monospace', minWidth: 24,
        }}>
          {String(pair.index).padStart(2, '0')}
        </Typography>

        {/* Status icon */}
        <Icon sx={{ fontSize: 18, color: cfg.color, flexShrink: 0 }} />

        {/* Source → Target labels */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
            <Tooltip title={pair.source_label}>
              <Typography sx={{
                fontSize: '0.78rem', fontWeight: 600, color: '#1E293B',
                fontFamily: '"JetBrains Mono", monospace',
                maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {srcShort}
              </Typography>
            </Tooltip>
            <CompareArrowsRoundedIcon sx={{ fontSize: 14, color: '#94A3B8' }} />
            <Tooltip title={pair.target_label}>
              <Typography sx={{
                fontSize: '0.78rem', fontWeight: 600, color: '#1E293B',
                fontFamily: '"JetBrains Mono", monospace',
                maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {tgtShort}
              </Typography>
            </Tooltip>
          </Box>
          {/* Mini check chips */}
          {!expanded && checks.length > 0 && (
            <Box sx={{ display: 'flex', gap: 0.5, mt: 0.75, flexWrap: 'wrap' }}>
              {checks.map((c, i) => <CheckChip key={i} check={c} />)}
            </Box>
          )}
        </Box>

        {/* Score + duration */}
        {summary.quality_score != null && (
          <Chip
            label={`${Math.round(summary.quality_score)}%`}
            size="small"
            sx={{
              height: 22, fontSize: '0.7rem', fontWeight: 700,
              bgcolor: summary.quality_score >= 90 ? '#ECFDF5' : summary.quality_score >= 70 ? '#FFFBEB' : '#FEF2F2',
              color: summary.quality_score >= 90 ? '#059669' : summary.quality_score >= 70 ? '#D97706' : '#DC2626',
              border: `1px solid ${summary.quality_score >= 90 ? '#05966920' : summary.quality_score >= 70 ? '#D9770620' : '#DC262620'}`,
            }}
          />
        )}
        {summary.duration_s != null && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.4 }}>
            <TimerRoundedIcon sx={{ fontSize: 12, color: '#94A3B8' }} />
            <Typography sx={{ fontSize: '0.68rem', color: '#94A3B8', fontFamily: 'monospace' }}>
              {summary.duration_s}s
            </Typography>
          </Box>
        )}

        <ExpandMoreRoundedIcon sx={{
          fontSize: 18, color: '#94A3B8', flexShrink: 0,
          transition: 'transform 0.2s',
          transform: expanded ? 'rotate(180deg)' : 'none',
        }} />
      </Box>

      {/* Expanded content — check details */}
      <Collapse in={expanded}>
        <Box sx={{ borderTop: '1px solid rgba(15,23,42,0.06)', px: 2.5, py: 2 }}>
          {pair.error && (
            <Box sx={{ p: 2, borderRadius: '8px', bgcolor: '#FEF2F2', border: '1px solid #FEE2E2', mb: 2 }}>
              <Typography sx={{ fontSize: '0.78rem', color: '#DC2626', fontWeight: 600 }}>
                Error: {pair.error}
              </Typography>
            </Box>
          )}
          {checks.length > 0 ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {checks.map((check, i) => {
                const checkCfg = STATUS[check.status] || STATUS.Pass;
                const CheckIcon = checkCfg.icon;
                const metrics = check.metrics || {};
                const metricKeys = Object.keys(metrics).filter(k => !k.startsWith('_'));
                return (
                  <Box key={i} sx={{
                    p: 2, borderRadius: '8px',
                    bgcolor: checkCfg.bg,
                    border: `1px solid ${checkCfg.color}15`,
                  }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: metricKeys.length > 0 ? 1.25 : 0 }}>
                      <CheckIcon sx={{ fontSize: 15, color: checkCfg.color }} />
                      <Typography sx={{ fontSize: '0.78rem', fontWeight: 700, color: checkCfg.color }}>
                        {fmtType(check.check_type)}
                      </Typography>
                      <Typography sx={{ fontSize: '0.72rem', color: '#64748B', flex: 1 }}>
                        {check.message}
                      </Typography>
                    </Box>
                    {metricKeys.length > 0 && (
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                        {metricKeys.map((k) => (
                          <Box key={k} sx={{
                            px: 1.25, py: 0.5, borderRadius: '6px',
                            bgcolor: 'rgba(255,255,255,0.6)',
                            border: '1px solid rgba(15,23,42,0.06)',
                          }}>
                            <Typography sx={{ fontSize: '0.62rem', color: '#94A3B8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                              {fmtMetric(k)}
                            </Typography>
                            <Typography sx={{ fontSize: '0.78rem', fontWeight: 700, color: '#1E293B', fontFamily: '"JetBrains Mono", monospace' }}>
                              {fmtVal(metrics[k])}
                            </Typography>
                          </Box>
                        ))}
                      </Box>
                    )}
                  </Box>
                );
              })}
            </Box>
          ) : !pair.error && (
            <Typography sx={{ fontSize: '0.78rem', color: '#94A3B8' }}>No check data available</Typography>
          )}

          {/* Link to full detail view */}
          {result?.run_id && (
            <Box sx={{ mt: 2, pt: 1.5, borderTop: '1px solid rgba(15,23,42,0.06)' }}>
              <Button
                size="small" variant="text"
                onClick={(e) => { e.stopPropagation(); window.open(`/results/${result.run_id}`, '_blank'); }}
                sx={{ fontSize: '0.72rem', color: '#3171D6', fontWeight: 600, textTransform: 'none' }}
              >
                View full report →
              </Button>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  );
}

/* ── Main Component ─────────────────────────────────────── */
export default function SuiteResultsView({ result }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const [copied, setCopied] = useState(false);

  const summary = result.summary || {};
  const pairs = result.test_cases || result.pairs || [];
  const score = summary.quality_score ?? 0;

  const filteredPairs = useMemo(() => {
    if (filter === 'all') return pairs;
    if (filter === 'failed') return pairs.filter(p => p.status === 'Fail' || p.status === 'Error');
    return pairs.filter(p => p.status === 'Pass');
  }, [pairs, filter]);

  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${result.suite_name || 'batch'}_report.json`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  }, [result]);

  const overallStatus = summary.overall_status || 'Pass';

  return (
    <Box sx={{ height: '100%', overflowY: 'auto' }}>
      {/* ── Top banner ──────────────────────────────────── */}
      <Box sx={{
        background: overallStatus === 'Pass'
          ? 'linear-gradient(135deg, #059669 0%, #10B981 100%)'
          : overallStatus === 'Fail'
          ? 'linear-gradient(135deg, #B91C1C 0%, #DC2626 100%)'
          : 'linear-gradient(135deg, #B45309 0%, #D97706 100%)',
        px: 4, py: 2.5,
        display: 'flex', alignItems: 'center', gap: 2.5,
      }}>
        <IconButton onClick={() => navigate('/suite')} size="small"
          sx={{ bgcolor: 'rgba(255,255,255,0.15)', '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' } }}>
          <ArrowBackRoundedIcon sx={{ color: '#fff', fontSize: 18 }} />
        </IconButton>

        <ScoreRing score={score} />

        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff', lineHeight: 1.2 }}>
            Suite {overallStatus === 'Pass' ? 'Passed' : 'Failed'}
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.7)', mt: 0.25 }}>
            {result.suite_name || 'Test Suite'} · {summary.total_test_cases || summary.total_pairs} test cases · {result.duration_s}s
          </Typography>
        </Box>

        {/* Action buttons */}
        <Box sx={{ display: 'flex', gap: 0.75 }}>
          <Tooltip title="Export JSON">
            <IconButton onClick={exportJson} size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.15)', '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' } }}>
              <DataObjectRoundedIcon sx={{ color: '#fff', fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>

        {/* Summary pills */}
        <Box sx={{ display: 'flex', gap: 1 }}>
          <StatPill label="test cases" value={summary.total_test_cases || summary.total_pairs} />
          <StatPill label="passed" value={summary.passed_test_cases || summary.passed_pairs} />
          {(summary.failed_test_cases || summary.failed_pairs) > 0 && <StatPill label="failed" value={summary.failed_test_cases || summary.failed_pairs} bold />}
          {(summary.error_test_cases || summary.error_pairs) > 0 && <StatPill label="errors" value={summary.error_test_cases || summary.error_pairs} bold />}
        </Box>
      </Box>

      {/* ── Content ─────────────────────────────────────── */}
      <Box sx={{ px: 4, py: 3 }}>
        {/* Summary cards row */}
        <Box sx={{ display: 'flex', gap: 2, mb: 2.5, flexWrap: 'wrap' }}>
          {/* Narrative summary */}
          <Box sx={{
            flex: '1 1 300px', bgcolor: '#fff', borderRadius: '12px', p: 2,
            border: '1px solid rgba(15,23,42,0.06)', boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
          }}>
            <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', mb: 1 }}>
              Summary
            </Typography>
            <Typography sx={{ fontSize: '0.82rem', color: '#334155', lineHeight: 1.7 }}>
              {summary.overall_status === 'Pass'
                ? `All ${summary.total_test_cases || summary.total_pairs} test cases passed validation across ${summary.total_checks} total checks (quality score: ${score}%). Your batch pipeline is healthy.`
                : `${(summary.failed_test_cases || summary.failed_pairs) + (summary.error_test_cases || summary.error_pairs)} of ${summary.total_test_cases || summary.total_pairs} test cases have issues. ${summary.failed_checks + summary.error_checks} of ${summary.total_checks} individual checks failed (quality score: ${score}%).`
              }
            </Typography>
          </Box>

          {/* Stats grid */}
          <Box sx={{
            flex: '0 0 280px', bgcolor: '#fff', borderRadius: '12px', p: 2,
            border: '1px solid rgba(15,23,42,0.06)', boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
          }}>
            <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', mb: 1 }}>
              Breakdown
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
              {[
                { label: 'Suite', value: result.suite_name || 'Test Suite' },
                { label: 'Total duration', value: `${result.duration_s}s` },
                { label: 'Total checks', value: `${summary.total_checks}` },
                { label: 'Checks passed', value: `${summary.passed_checks}`, color: '#059669' },
                ...(summary.failed_checks > 0 ? [{ label: 'Checks failed', value: `${summary.failed_checks}`, color: '#DC2626' }] : []),
                ...(summary.error_checks > 0 ? [{ label: 'Check errors', value: `${summary.error_checks}`, color: '#D97706' }] : []),
              ].map(item => (
                <Box key={item.label} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography sx={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 500 }}>{item.label}</Typography>
                  <Typography sx={{ fontSize: '0.68rem', color: item.color || '#334155', fontWeight: 600 }}>{item.value}</Typography>
                </Box>
              ))}
            </Box>
          </Box>
        </Box>

        {/* Pass/Fail bar */}
        <Box sx={{ mb: 2.5, bgcolor: '#fff', borderRadius: '12px', p: 2, border: '1px solid rgba(15,23,42,0.06)', boxShadow: '0 1px 3px rgba(15,23,42,0.04)' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Test Case Results
            </Typography>
            <Box sx={{ flex: 1 }} />
            <Typography sx={{ fontSize: '0.68rem', color: '#059669', fontWeight: 600 }}>{summary.passed_test_cases || summary.passed_pairs} passed</Typography>
            {(summary.failed_test_cases || summary.failed_pairs) > 0 && <Typography sx={{ fontSize: '0.68rem', color: '#DC2626', fontWeight: 600 }}>{summary.failed_test_cases || summary.failed_pairs} failed</Typography>}
            {(summary.error_test_cases || summary.error_pairs) > 0 && <Typography sx={{ fontSize: '0.68rem', color: '#D97706', fontWeight: 600 }}>{summary.error_test_cases || summary.error_pairs} errors</Typography>}
          </Box>
          <Box sx={{ display: 'flex', height: 8, borderRadius: '4px', overflow: 'hidden', bgcolor: '#F1F5F9' }}>
            {(summary.passed_test_cases || summary.passed_pairs) > 0 && (
              <Box sx={{ width: `${((summary.passed_test_cases || summary.passed_pairs) / (summary.total_test_cases || summary.total_pairs)) * 100}%`, bgcolor: '#059669', transition: 'width 0.5s ease' }} />
            )}
            {(summary.failed_test_cases || summary.failed_pairs) > 0 && (
              <Box sx={{ width: `${((summary.failed_test_cases || summary.failed_pairs) / (summary.total_test_cases || summary.total_pairs)) * 100}%`, bgcolor: '#DC2626', transition: 'width 0.5s ease' }} />
            )}
            {(summary.error_test_cases || summary.error_pairs) > 0 && (
              <Box sx={{ width: `${((summary.error_test_cases || summary.error_pairs) / (summary.total_test_cases || summary.total_pairs)) * 100}%`, bgcolor: '#D97706', transition: 'width 0.5s ease' }} />
            )}
          </Box>
        </Box>

        {/* Filter bar */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2.5 }}>
          <Typography sx={{ fontSize: '0.95rem', fontWeight: 800, color: '#0F172A' }}>
            Test Case Details
            {((summary.failed_test_cases || summary.failed_pairs) + (summary.error_test_cases || summary.error_pairs)) > 0 && (
              <Typography component="span" sx={{ fontSize: '0.75rem', fontWeight: 600, color: '#DC2626', ml: 1 }}>
                {(summary.failed_test_cases || summary.failed_pairs) + (summary.error_test_cases || summary.error_pairs)} issue{((summary.failed_test_cases || summary.failed_pairs) + (summary.error_test_cases || summary.error_pairs)) !== 1 ? 's' : ''}
              </Typography>
            )}
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {[
              { key: 'all', label: 'All', count: pairs.length },
              { key: 'failed', label: 'Issues', count: pairs.filter(p => p.status !== 'Pass').length },
              { key: 'passed', label: 'Passed', count: pairs.filter(p => p.status === 'Pass').length },
            ].map(f => (
              <Box key={f.key} onClick={() => setFilter(f.key)} sx={{
                px: 1.25, py: 0.4, borderRadius: '6px', cursor: 'pointer',
                bgcolor: filter === f.key ? '#3171D6' : 'transparent',
                transition: 'all 0.15s',
                '&:hover': { bgcolor: filter === f.key ? '#2563EB' : '#F1F5F9' },
              }}>
                <Typography sx={{
                  fontSize: '0.72rem', fontWeight: 600,
                  color: filter === f.key ? '#fff' : '#64748B',
                }}>
                  {f.label} ({f.count})
                </Typography>
              </Box>
            ))}
          </Box>
        </Box>

        {/* Test case cards */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {filteredPairs.map((pair) => (
            <TestCaseCard
              key={pair.index}
              pair={pair}
              defaultOpen={pair.status !== 'Pass'}
            />
          ))}
          {filteredPairs.length === 0 && (
            <Box sx={{ py: 8, textAlign: 'center' }}>
              <Typography sx={{ color: '#94A3B8' }}>No test cases match this filter</Typography>
            </Box>
          )}
        </Box>
      </Box>

      <Snackbar open={copied} autoHideDuration={2000} onClose={() => setCopied(false)} message="Copied" />
    </Box>
  );
}
