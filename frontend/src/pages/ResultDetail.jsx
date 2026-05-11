import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Box, Typography, Chip, IconButton, Collapse,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Button, CircularProgress, Tooltip, Snackbar,
} from '@mui/material';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import PictureAsPdfRoundedIcon from '@mui/icons-material/PictureAsPdfRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import TimerRoundedIcon from '@mui/icons-material/TimerRounded';
import DataObjectRoundedIcon from '@mui/icons-material/DataObjectRounded';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import { useNavigate, useParams } from 'react-router-dom';
import { getRunResult } from '../api';

/* ── constants ────────────────────────────────────────────── */

const S = {
  Pass:  { color: '#059669', bg: '#ECFDF5', bgStrong: '#D1FAE5', icon: CheckCircleRoundedIcon, label: 'PASS' },
  Fail:  { color: '#DC2626', bg: '#FEF2F2', bgStrong: '#FEE2E2', icon: CancelRoundedIcon, label: 'FAIL' },
  Error: { color: '#D97706', bg: '#FFFBEB', bgStrong: '#FEF3C7', icon: ErrorOutlineRoundedIcon, label: 'ERROR' },
  Warning: { color: '#D97706', bg: '#FFFBEB', bgStrong: '#FEF3C7', icon: WarningAmberRoundedIcon, label: 'WARN' },
};

const METRIC_LABELS = {
  src_row_count: 'Source rows', tgt_row_count: 'Target rows',
  row_count_diff: 'Difference', pct_diff: '% difference',
  mismatched_null_columns: 'Columns with null mismatches',
  mismatched_columns: 'Type/nullable mismatches',
  src_column_count: 'Source columns', tgt_column_count: 'Target columns',
  columns_only_in_source: 'Only in source', columns_only_in_target: 'Only in target',
  rows_only_in_source: 'Rows only in source', rows_only_in_target: 'Rows only in target',
  rows_with_diffs: 'Rows with differences', cell_diffs_found: 'Cell-level diffs',
  match_pct: 'Match %', diff_columns: 'Columns affected',
  value_mismatches: 'Value mismatches', mismatch_count: 'Mismatches',
  duplicate_rows_src: 'Duplicates (source)', duplicate_rows_tgt: 'Duplicates (target)',
};
const fmtMetric = (k) => METRIC_LABELS[k] || k.replace(/_/g, ' ');
const fmtType = (t) => ({ row_count: 'Row Count', metadata: 'Schema / Metadata', null_check: 'Null Analysis', data: 'Data Comparison', duplicate: 'Duplicate Check' }[t] || t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
const fmtVal = (v) => v === null || v === undefined ? '—' : typeof v === 'number' ? v.toLocaleString() : String(v);

const COL_HEADERS = {
  COLUMN: 'Column', SOURCE_VALUE: 'Source Value', TARGET_VALUE: 'Target Value',
  ID: 'Row Key', STATUS: 'Status', DIFF_TYPE: 'Type',
  SRC_DATA_TYPE: 'Source Type', TGT_DATA_TYPE: 'Target Type',
  DATA_TYPE_MATCH: 'Type Match', SRC_NULLABLE: 'Src Nullable', TGT_NULLABLE: 'Tgt Nullable',
  NULLABLE_MATCH: 'Nullable Match', SRC_NULLS: 'Source Nulls', TGT_NULLS: 'Target Nulls',
  DIFF: 'Difference', SRC_NULL_PCT: 'Source %', TGT_NULL_PCT: 'Target %',
};
const fmtCol = (c) => COL_HEADERS[c] || c;

/* ── Check type descriptions for business users ──────────── */
const CHECK_DESC = {
  row_count: 'Compares the number of rows between source and target tables',
  metadata: 'Compares column names, data types, and nullable settings',
  null_check: 'Compares null value counts per column between source and target',
  data: 'Row-by-row and cell-by-cell comparison of actual data values',
  duplicate: 'Checks for duplicate rows in source and target',
};



/* ── Severity inference from check metrics ──────────────── */
const SEVERITY = {
  critical: { label: 'Critical', color: '#DC2626', bg: '#FEF2F2', icon: '🔴' },
  high:     { label: 'High',     color: '#EA580C', bg: '#FFF7ED', icon: '🟠' },
  medium:   { label: 'Medium',   color: '#D97706', bg: '#FFFBEB', icon: '🟡' },
  low:      { label: 'Low',      color: '#059669', bg: '#ECFDF5', icon: '🟢' },
};
function inferSeverity(check) {
  if (check.status === 'Pass') return SEVERITY.low;
  const m = check.metrics || {};
  if (check.check_type === 'data') {
    const matchPct = m.match_pct ?? 100;
    if (matchPct <= 50) return SEVERITY.critical;
    if (matchPct < 80) return SEVERITY.high;
    return SEVERITY.medium;
  }
  if (check.check_type === 'row_count') {
    const pctDiff = Math.abs(m.pct_diff ?? 0);
    if (pctDiff > 20) return SEVERITY.critical;
    if (pctDiff > 5) return SEVERITY.high;
    return SEVERITY.medium;
  }
  if (check.check_type === 'null_check') {
    const mismatched = m.mismatched_null_columns ?? 0;
    if (mismatched > 5) return SEVERITY.critical;
    if (mismatched > 2) return SEVERITY.high;
    return SEVERITY.medium;
  }
  return SEVERITY.medium;
}

/* ── Actionable recommendations per check type ───────────── */
function getRecommendation(check) {
  if (check.status === 'Pass') return null;
  const m = check.metrics || {};
  switch (check.check_type) {
    case 'data':
      if (m.match_pct != null && m.match_pct <= 50) return 'Very low match rate — verify key cols are correct and data was loaded from the same snapshot.';
      if (m.mismatch_columns) return `Focus investigation on columns: ${m.mismatch_columns}. Check for transformation logic or encoding differences.`;
      return 'Review the diff table below. Filter by column to identify systematic patterns.';
    case 'row_count':
      if (m.row_count_diff > 0) return 'Target has fewer rows than source — check for failed inserts, filtering logic, or incomplete loads.';
      if (m.row_count_diff < 0) return 'Target has more rows — check for duplicate inserts or missing deduplication logic.';
      return 'Row counts diverged — verify the ETL load completed successfully.';
    case 'metadata':
      return 'Schema mismatch detected — review column type changes. This may indicate an upstream schema migration.';
    case 'null_check':
      return 'Null count mismatch — check for coalesce/default-value logic differences or missing NOT NULL constraints.';
    case 'duplicate':
      return 'Duplicates found — verify primary key constraints and deduplication steps in the pipeline.';
    default:
      return 'Review the details below to understand the failure.';
  }
}

/* ── Natural language summary generator ──────────────────── */
function generateSummary(summary, checks) {
  const { total, passed, failed, errors } = summary;
  const failedChecks = checks.filter(c => c.status === 'Fail' || c.status === 'Error');
  const score = Math.round(summary.quality_score ?? 100);
  
  if (failed === 0 && errors === 0) {
    return `All ${total} validation checks passed with a quality score of ${score}%. Your data pipeline is healthy.`;
  }
  
  const parts = [];
  if (failed > 0) parts.push(`${failed} check${failed !== 1 ? 's' : ''} failed`);
  if (errors > 0) parts.push(`${errors} error${errors !== 1 ? 's' : ''}`);
  
  const criticalChecks = failedChecks.filter(c => inferSeverity(c) === SEVERITY.critical);
  let msg = `${parts.join(' and ')} out of ${total} total checks (score: ${score}%).`;
  
  if (criticalChecks.length > 0) {
    msg += ` ${criticalChecks.length} critical issue${criticalChecks.length !== 1 ? 's' : ''} need${criticalChecks.length === 1 ? 's' : ''} immediate attention:`;
    msg += ' ' + criticalChecks.map(c => fmtType(c.check_type)).join(', ') + '.';
  }
  
  return msg;
}

/* ── Quality Score Ring (MC-style) ───────────────────────── */
function ScoreRing({ score, size = 56 }) {
  const r = (size / 2) - 5;
  const circ = 2 * Math.PI * r;
  const color = score >= 90 ? '#059669' : score >= 70 ? '#D97706' : '#DC2626';
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

/* ── Execution Timeline (collapsible, horizontal bar chart) ─ */
function ExecutionTimeline({ timings, checks }) {
  const [expanded, setExpanded] = useState(false);
  if (!timings || timings.length === 0) return null;
  const maxDur = Math.max(...timings.map(t => t.duration_s), 0.01);
  const totalDur = timings.reduce((s, t) => s + t.duration_s, 0);

  return (
    <Box sx={{
      bgcolor: '#fff', borderRadius: '12px', mb: 2.5,
      border: '1px solid rgba(15,23,42,0.06)',
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      overflow: 'hidden',
    }}>
      <Box
        onClick={() => setExpanded(!expanded)}
        sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2.5, py: 1.5, cursor: 'pointer', '&:hover': { bgcolor: '#FAFBFC' }, transition: 'background 0.15s' }}
      >
        <TimerRoundedIcon sx={{ fontSize: 15, color: '#94A3B8' }} />
        <Typography sx={{ fontSize: '0.72rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Execution Timeline
        </Typography>
        {/* Mini stacked bar when collapsed */}
        <Box sx={{ flex: 1, display: 'flex', height: 6, borderRadius: '3px', overflow: 'hidden', mx: 2, bgcolor: '#F1F5F9' }}>
          {timings.map((t, i) => {
            const pct = totalDur > 0 ? (t.duration_s / totalDur) * 100 : 0;
            const checkObj = checks?.find(c => c.check_type === t.check_type);
            const cfg = S[checkObj?.status] || S.Pass;
            return (
              <Box key={i} sx={{
                width: pct + '%', minWidth: pct > 0 ? 2 : 0, height: '100%',
                bgcolor: cfg.color, opacity: 0.6,
                borderRight: i < timings.length - 1 ? '1px solid #fff' : 'none',
              }} />
            );
          })}
        </Box>
        <Typography sx={{ fontSize: '0.68rem', color: '#94A3B8', fontFamily: '"JetBrains Mono", monospace', flexShrink: 0 }}>
          {totalDur.toFixed(2)}s
        </Typography>
        <ExpandMoreRoundedIcon sx={{ fontSize: 16, color: '#94A3B8', transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none' }} />
      </Box>
      <Collapse in={expanded} timeout="auto">
        <Box sx={{ px: 2.5, pb: 2 }}>
          {/* Individual bars */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            {timings.map((t, i) => {
              const checkObj = checks?.find(c => c.check_type === t.check_type);
              const cfg = S[checkObj?.status] || S.Pass;
              const pct = maxDur > 0 ? (t.duration_s / maxDur) * 100 : 0;
              return (
                <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                  <Typography sx={{ fontSize: '0.72rem', fontWeight: 600, color: '#334155', width: 110, flexShrink: 0 }}>
                    {fmtType(t.check_type)}
                  </Typography>
                  <Box sx={{ flex: 1, height: 8, bgcolor: '#F1F5F9', borderRadius: 4, overflow: 'hidden' }}>
                    <Box sx={{ height: '100%', width: Math.max(pct, 2) + '%', bgcolor: cfg.color, borderRadius: 4, opacity: 0.7, transition: 'width 0.5s' }} />
                  </Box>
                  <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#64748B', fontFamily: '"JetBrains Mono", monospace', width: 50, textAlign: 'right', flexShrink: 0 }}>
                    {t.duration_s.toFixed(3)}s
                  </Typography>
                </Box>
              );
            })}
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
}

/* ── Metric value — highlights bad values ────────────────── */
function MetricValue({ k, v }) {
  const isBad = (k.includes('diff') || k.includes('mismatch') || k.includes('only')) && v !== 0 && v !== '' && v !== '0';
  const isGoodPct = k === 'match_pct';
  let color = '#334155';
  if (isBad) color = '#DC2626';
  if (isGoodPct) color = v >= 90 ? '#059669' : v >= 70 ? '#D97706' : '#DC2626';
  const display = typeof v === 'number' ? (k.includes('pct') || k === 'match_pct' ? `${v}%` : v.toLocaleString()) : (v === '' ? '—' : String(v));
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.5, px: 0, borderBottom: '1px solid rgba(15,23,42,0.04)' }}>
      <Typography sx={{ fontSize: '0.8rem', color: '#64748B' }}>{fmtMetric(k)}</Typography>
      <Typography sx={{ fontSize: '0.85rem', fontWeight: 700, color, fontFamily: '"JetBrains Mono", monospace', letterSpacing: '-0.02em' }}>{display}</Typography>
    </Box>
  );
}

/* ── Comparison stat — side-by-side source/target ────────── */
/* ── Stat item for metric strips ──────────────────────────── */
function Stat({ label, value, sub, color, accent }) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.15 }}>
      <Typography sx={{ fontSize: '0.56rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.05em', lineHeight: 1 }}>
        {label}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5 }}>
        <Typography sx={{
          fontSize: '0.92rem', fontWeight: 700, color: color || '#1E293B',
          fontFamily: '"JetBrains Mono", monospace', lineHeight: 1.2,
        }}>
          {value}
        </Typography>
        {sub && (
          <Typography sx={{ fontSize: '0.62rem', color: '#94A3B8', fontWeight: 500 }}>{sub}</Typography>
        )}
      </Box>
      {accent !== undefined && (
        <Box sx={{ width: 24, height: 2, borderRadius: 1, bgcolor: accent, mt: 0.15 }} />
      )}
    </Box>
  );
}

/* ── Divider between stats ───────────────────────────────── */
function StatDivider() {
  return <Box sx={{ width: '1px', alignSelf: 'stretch', bgcolor: 'rgba(148,163,184,0.12)', mx: 0.5 }} />;
}

/* ── Row Count Summary ───────────────────────────────────── */
function RowCountSummary({ metrics }) {
  const src = metrics.src_row_count ?? metrics.src_rows ?? 0;
  const tgt = metrics.tgt_row_count ?? metrics.tgt_rows ?? 0;
  const diff = metrics.row_count_diff ?? metrics.diff ?? Math.abs(src - tgt);
  const pctDiff = metrics.pct_diff ?? (src > 0 ? ((diff / src) * 100).toFixed(1) : 0);
  const ok = diff === 0;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.5 }}>
      <Stat label="Source rows" value={src.toLocaleString()} accent="#3B82F6" />
      <StatDivider />
      <Stat label="Target rows" value={tgt.toLocaleString()} accent="#059669" />
      <StatDivider />
      <Stat label="Difference" value={diff.toLocaleString()} color={ok ? '#059669' : '#DC2626'} />
      <StatDivider />
      <Stat label="% Diff" value={`${pctDiff}%`} color={ok ? '#059669' : '#DC2626'} />
      {ok && (
        <Typography sx={{ fontSize: '0.72rem', color: '#059669', ml: 0.5 }}>✓</Typography>
      )}
    </Box>
  );
}

/* ── Schema Summary ──────────────────────────────────────── */
function SchemaSummary({ metrics }) {
  const srcCols = metrics.src_column_count ?? metrics.src_columns ?? 0;
  const tgtCols = metrics.tgt_column_count ?? metrics.tgt_columns ?? 0;
  const onlySrcRaw = metrics.columns_only_in_source ?? '';
  const onlyTgtRaw = metrics.columns_only_in_target ?? '';
  const onlySrc = typeof onlySrcRaw === 'string' ? (onlySrcRaw.trim() ? onlySrcRaw.split(',').length : 0) : (onlySrcRaw || 0);
  const onlyTgt = typeof onlyTgtRaw === 'string' ? (onlyTgtRaw.trim() ? onlyTgtRaw.split(',').length : 0) : (onlyTgtRaw || 0);
  const mismatches = metrics.mismatched_columns ?? metrics.type_nullable_mismatches ?? 0;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.5 }}>
      <Stat label="Source cols" value={srcCols} accent="#3B82F6" />
      <StatDivider />
      <Stat label="Target cols" value={tgtCols} accent="#059669" />
      <StatDivider />
      <Stat label="Only in source" value={onlySrc || '—'} color={onlySrc > 0 ? '#DC2626' : '#64748B'} />
      <StatDivider />
      <Stat label="Only in target" value={onlyTgt || '—'} color={onlyTgt > 0 ? '#DC2626' : '#64748B'} />
      <StatDivider />
      <Stat label="Type mismatches" value={mismatches} color={mismatches > 0 ? '#DC2626' : '#059669'} />
    </Box>
  );
}

/* ── Null Analysis Summary ───────────────────────────────── */
function NullSummary({ metrics }) {
  const cols = metrics.mismatched_null_columns ?? metrics.null_mismatch_columns ?? 0;
  const ok = cols === 0;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.5 }}>
      <Stat label="Columns with null mismatches" value={cols} color={ok ? '#059669' : '#DC2626'} />
      <Typography sx={{ fontSize: '0.68rem', color: '#64748B' }}>
        {ok ? '— all columns match' : `— ${cols} column${cols !== 1 ? 's' : ''} differ`}
      </Typography>
    </Box>
  );
}

/* ── Data Comparison Summary ─────────────────────────────── */
function DataSummary({ metrics }) {
  const srcRows = metrics.src_row_count ?? metrics.src ?? 0;
  const tgtRows = metrics.tgt_row_count ?? metrics.tgt ?? 0;
  const onlySrc = metrics.rows_only_in_source ?? metrics.only_src ?? 0;
  const onlyTgt = metrics.rows_only_in_target ?? metrics.only_tgt ?? 0;
  const diffRows = metrics.rows_with_diffs ?? metrics.diff_rows ?? 0;
  const cellDiffs = metrics.cell_diffs_found ?? metrics.cell_diffs ?? 0;
  const matchPct = metrics.match_pct ?? 0;
  const mismatchCols = metrics.mismatch_columns ?? '';
  const colSummary = metrics.column_mismatch_summary ?? '';
  const colList = typeof mismatchCols === 'string' ? mismatchCols.split(',').map(s => s.trim()).filter(Boolean) : [];
  const matchColor = matchPct >= 90 ? '#059669' : matchPct >= 70 ? '#D97706' : '#DC2626';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {/* Match % hero + row counts */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5, mr: 0.5 }}>
          <Typography sx={{ fontSize: '1.4rem', fontWeight: 800, color: matchColor, fontFamily: '"JetBrains Mono", monospace', lineHeight: 1 }}>
            {matchPct}%
          </Typography>
          <Typography sx={{ fontSize: '0.56rem', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase' }}>match</Typography>
        </Box>
        <StatDivider />
        <Stat label="Source rows" value={srcRows.toLocaleString()} accent="#3B82F6" />
        <StatDivider />
        <Stat label="Target rows" value={tgtRows.toLocaleString()} accent="#059669" />
        <StatDivider />
        <Stat label="Only in src" value={onlySrc.toLocaleString()} color={onlySrc > 0 ? '#DC2626' : '#64748B'} />
        <StatDivider />
        <Stat label="Only in tgt" value={onlyTgt.toLocaleString()} color={onlyTgt > 0 ? '#DC2626' : '#64748B'} />
        <StatDivider />
        <Stat label="Row diffs" value={diffRows.toLocaleString()} color={diffRows > 0 ? '#DC2626' : '#059669'} />
        <StatDivider />
        <Stat label="Cell diffs" value={cellDiffs.toLocaleString()} color={cellDiffs > 0 ? '#DC2626' : '#059669'} />
      </Box>
      {/* Mismatch column chips */}
      {colList.length > 0 && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
          <Typography sx={{ fontSize: '0.56rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.05em', mr: 0.25 }}>
            Affected columns
          </Typography>
          {colList.map(c => {
            const summaryStr = typeof colSummary === 'string' ? colSummary : '';
            const match = summaryStr.match(new RegExp(c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ':(\\d+)'));
            const cnt = match ? match[1] : '';
            return (
              <Chip key={c} label={cnt ? `${c} · ${cnt}` : c} size="small" sx={{
                height: 20, fontSize: '0.6rem', fontWeight: 600,
                bgcolor: '#FEF2F2', color: '#B91C1C', border: '1px solid rgba(220,38,38,0.12)',
                fontFamily: '"JetBrains Mono", monospace',
              }} />
            );
          })}
        </Box>
      )}
    </Box>
  );
}

/* ── Check Summary Router — picks the right summary view ── */
function CheckSummary({ check }) {
  const m = check.metrics || {};
  switch (check.check_type) {
    case 'row_count': return <RowCountSummary metrics={m} />;
    case 'metadata': return <SchemaSummary metrics={m} />;
    case 'null_check': return <NullSummary metrics={m} />;
    case 'data': return <DataSummary metrics={m} />;
    default: return null;
  }
}

/* ── Diff table with coloring + pagination ─────────────── */
const PAGE_SIZE = 50;
function DiffTable({ details, total }) {
  const [page, setPage] = useState(0);
  if (!details || details.length === 0) return null;
  const cols = Object.keys(details[0]);
  const hasSrcTgt = cols.some(c => /SOURCE_VALUE|source_value/i.test(c));
  const totalRows = details.length;
  const totalPages = Math.ceil(totalRows / PAGE_SIZE);
  const start = page * PAGE_SIZE;
  const pageRows = details.slice(start, start + PAGE_SIZE);
  const grandTotal = total || totalRows;
  return (
    <Box sx={{ borderTop: '1px solid rgba(15,23,42,0.06)' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', px: 2.5, py: 1, bgcolor: '#F8FAFC' }}>
        <Typography sx={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 500 }}>
          Showing {start + 1}–{Math.min(start + PAGE_SIZE, totalRows)} of {grandTotal.toLocaleString()} differences
          {grandTotal > totalRows && (
            <Typography component="span" sx={{ fontSize: '0.65rem', color: '#94A3B8', ml: 0.5 }}>
              ({totalRows.toLocaleString()} loaded)
            </Typography>
          )}
        </Typography>
        {hasSrcTgt && (
          <Box sx={{ display: 'flex', gap: 2.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 10, height: 3, borderRadius: 1, bgcolor: '#DC2626' }} />
              <Typography sx={{ fontSize: '0.65rem', color: '#94A3B8' }}>Source</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 10, height: 3, borderRadius: 1, bgcolor: '#059669' }} />
              <Typography sx={{ fontSize: '0.65rem', color: '#94A3B8' }}>Target</Typography>
            </Box>
          </Box>
        )}
      </Box>
      <TableContainer sx={{ maxHeight: 480 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {cols.map(c => (
                <TableCell key={c} sx={{
                  fontSize: '0.68rem', fontWeight: 700, color: '#475569',
                  textTransform: 'none', letterSpacing: '0.01em',
                  bgcolor: '#F1F5F9', py: 0.75, px: 1.5,
                  borderBottom: '2px solid #E2E8F0',
                  whiteSpace: 'nowrap',
                }}>{fmtCol(c)}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {pageRows.map((row, i) => (
              <TableRow key={start + i} sx={{ '&:hover': { bgcolor: 'rgba(49,113,214,0.02)' } }}>
                {cols.map(c => {
                  const isSrc = /SOURCE_VALUE|source_value|SRC_DATA_TYPE|SRC_NULLS|SRC_NULL_PCT/i.test(c);
                  const isTgt = /TARGET_VALUE|target_value|TGT_DATA_TYPE|TGT_NULLS|TGT_NULL_PCT/i.test(c);
                  const isBool = row[c] === true || row[c] === false;
                  const isFalseBool = row[c] === false;
                  return (
                    <TableCell key={c} sx={{
                      fontSize: '0.78rem', py: 0.6, px: 1.5,
                      fontFamily: '"JetBrains Mono", monospace',
                      color: isFalseBool ? '#DC2626' : isSrc ? '#B91C1C' : isTgt ? '#047857' : '#334155',
                      fontWeight: (isSrc || isTgt || isFalseBool) ? 600 : 400,
                      bgcolor: isSrc ? 'rgba(220,38,38,0.03)' : isTgt ? 'rgba(5,150,105,0.03)' : 'transparent',
                      borderBottom: '1px solid rgba(15,23,42,0.04)',
                      whiteSpace: 'nowrap',
                    }}>
                      {isBool ? (row[c] ? '✓' : '✗') : fmtVal(row[c])}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {/* Pagination controls */}
      {totalPages > 1 && (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, py: 1, bgcolor: '#F8FAFC', borderTop: '1px solid rgba(15,23,42,0.06)' }}>
          <Button size="small" disabled={page === 0} onClick={() => setPage(0)}
            sx={{ minWidth: 28, fontSize: '0.68rem', color: '#64748B', '&:disabled': { color: '#CBD5E1' } }}>
            ««
          </Button>
          <Button size="small" disabled={page === 0} onClick={() => setPage(p => p - 1)}
            sx={{ minWidth: 28, fontSize: '0.68rem', color: '#64748B', '&:disabled': { color: '#CBD5E1' } }}>
            ‹
          </Button>
          <Typography sx={{ fontSize: '0.72rem', color: '#475569', fontWeight: 600, mx: 1 }}>
            Page {page + 1} of {totalPages}
          </Typography>
          <Button size="small" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
            sx={{ minWidth: 28, fontSize: '0.68rem', color: '#64748B', '&:disabled': { color: '#CBD5E1' } }}>
            ›
          </Button>
          <Button size="small" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}
            sx={{ minWidth: 28, fontSize: '0.68rem', color: '#64748B', '&:disabled': { color: '#CBD5E1' } }}>
            »»
          </Button>
        </Box>
      )}
    </Box>
  );
}

/* ── Column impact summary (Datafold-inspired) ───────────── */
function ColumnImpact({ details }) {
  const colCounts = useMemo(() => {
    if (!details || details.length === 0) return [];
    const counts = {};
    details.forEach(row => {
      const col = row.COLUMN || row.column;
      if (col) counts[col] = (counts[col] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [details]);

  if (colCounts.length === 0) return null;
  const max = colCounts[0][1];

  return (
    <Box sx={{ mt: 1.5, mb: 0.5 }}>
      <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.05em', mb: 1 }}>
        Columns Affected
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {colCounts.map(([col, count]) => (
          <Box key={col} sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Typography sx={{ fontSize: '0.75rem', fontFamily: '"JetBrains Mono", monospace', color: '#334155', fontWeight: 600, width: 100, flexShrink: 0 }}>{col}</Typography>
            <Box sx={{ flex: 1, height: 6, bgcolor: '#F1F5F9', borderRadius: 3, overflow: 'hidden' }}>
              <Box sx={{ height: '100%', width: `${(count / max) * 100}%`, bgcolor: '#EF4444', borderRadius: 3, minWidth: 4, transition: 'width 0.3s' }} />
            </Box>
            <Typography sx={{ fontSize: '0.7rem', color: '#94A3B8', fontWeight: 600, minWidth: 20, textAlign: 'right' }}>{count}</Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

/* ── Single check card ───────────────────────────────────── */
function CheckCard({ check, defaultOpen, timing }) {
  const [open, setOpen] = useState(defaultOpen);
  const cfg = S[check.status] || S.Error;
  const Icon = cfg.icon;
  const hasDetails = check.details && check.details.length > 0;
  const metrics = check.metrics || {};
  const metricEntries = Object.entries(metrics);
  const isDataCheck = check.check_type === 'data';
  const hasColumnImpact = isDataCheck && hasDetails && check.details.some(r => r.COLUMN || r.column);
  const hasTypedSummary = ['row_count', 'metadata', 'null_check', 'data'].includes(check.check_type);

  return (
    <Box sx={{
      bgcolor: '#fff', borderRadius: '12px', overflow: 'hidden',
      border: `1px solid ${check.status === 'Pass' ? '#E2E8F0' : cfg.color + '22'}`,
      boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
    }}>
      {/* Status bar at top — thin colored line */}
      <Box sx={{ height: 3, bgcolor: cfg.color, opacity: 0.7 }} />

      {/* Header */}
      <Box sx={{ px: 2.5, pt: 1.5, pb: hasDetails ? 0 : 1.5 }}>
        {/* Title row */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: cfg.color, flexShrink: 0 }} />
          <Typography sx={{ fontSize: '0.95rem', fontWeight: 700, color: '#0F172A' }}>
            {fmtType(check.check_type)}
          </Typography>
          <Chip label={cfg.label} size="small" sx={{
            height: 16, fontSize: '0.52rem', fontWeight: 800, letterSpacing: '0.08em',
            bgcolor: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}22`,
          }} />
          {timing && (
            <Typography sx={{ ml: 'auto', fontSize: '0.65rem', color: '#94A3B8', fontFamily: '"JetBrains Mono", monospace', fontWeight: 600 }}>
              {timing.duration_s >= 1 ? `${timing.duration_s.toFixed(2)}s` : `${(timing.duration_s * 1000).toFixed(0)}ms`}
            </Typography>
          )}
        </Box>

        {!hasTypedSummary && check.message && (
          <Typography sx={{ fontSize: '0.75rem', color: '#64748B', lineHeight: 1.5, mb: 1 }}>
            {check.message}
          </Typography>
        )}

        {/* Type-specific summary OR generic fallback */}
        {hasTypedSummary ? (
          <Box sx={{ mb: 1.5 }}>
            <CheckSummary check={check} />
          </Box>
        ) : metricEntries.length > 0 ? (
          <Box sx={{
            display: 'grid', gridTemplateColumns: metricEntries.length > 3 ? '1fr 1fr' : '1fr',
            gap: '0 24px', mb: 1.5,
          }}>
            {metricEntries.map(([k, v]) => <MetricValue key={k} k={k} v={v} />)}
          </Box>
        ) : null}

        {/* Column impact for data checks — only show when no typed summary (chips already cover it) */}
        {hasColumnImpact && !hasTypedSummary && <ColumnImpact details={check.details} />}

        {/* Expand toggle */}
        {hasDetails && (
          <Box
            onClick={() => setOpen(!open)}
            sx={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              py: 1, cursor: 'pointer', gap: 0.75,
              borderTop: '1px solid rgba(15,23,42,0.04)', mt: 1,
              '&:hover': { bgcolor: 'rgba(49,113,214,0.02)' },
              transition: 'background 0.15s',
            }}
          >
            <Typography sx={{ fontSize: '0.72rem', fontWeight: 600, color: '#3171D6' }}>
              {open ? 'Hide' : 'View'} {check.details_total || check.details.length} difference{(check.details_total || check.details.length) !== 1 ? 's' : ''}
            </Typography>
            <ExpandMoreRoundedIcon sx={{
              fontSize: 16, color: '#3171D6',
              transition: 'transform 0.2s',
              transform: open ? 'rotate(180deg)' : 'none',
            }} />
          </Box>
        )}
      </Box>

      {/* Expandable diff table */}
      {hasDetails && (
        <Collapse in={open} timeout="auto" unmountOnExit>
          <DiffTable details={check.details} total={check.details_total} />
        </Collapse>
      )}
    </Box>
  );
}

/* ── Summary stat pill ───────────────────────────────────── */
function StatPill({ label, value, color, bold }) {
  return (
    <Box sx={{
      display: 'flex', alignItems: 'center', gap: 1, px: 2, py: 0.75,
      bgcolor: 'rgba(255,255,255,0.15)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)',
      backdropFilter: 'blur(4px)',
    }}>
      <Typography sx={{ fontSize: '1.1rem', fontWeight: 800, color: '#fff', lineHeight: 1, fontFamily: '"JetBrains Mono", monospace' }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.7)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {label}
      </Typography>
    </Box>
  );
}

/* ── Main component ──────────────────────────────────────── */

export default function ResultDetail({ result: propResult }) {
  const navigate = useNavigate();
  const { runId } = useParams();
  const [fetchedResult, setFetchedResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const reportRef = useRef(null);

  const exportPdf = useCallback(async () => {
    if (!reportRef.current) return;
    setExporting(true);
    try {
      const html2canvas = (await import('html2canvas')).default;
      const { jsPDF } = await import('jspdf');

      const el = reportRef.current;

      // Force full-height render for capture
      const origOverflow = el.style.overflow;
      const origHeight = el.style.height;
      const origMaxH = el.style.maxHeight;
      el.style.overflow = 'visible';
      el.style.height = 'auto';
      el.style.maxHeight = 'none';

      // Wait a tick for layout to settle
      await new Promise(r => setTimeout(r, 100));

      const canvas = await html2canvas(el, {
        scale: 1.5,
        useCORS: true,
        logging: false,
        backgroundColor: '#F8FAFC',
        width: el.scrollWidth,
        height: el.scrollHeight,
      });

      // Restore
      el.style.overflow = origOverflow;
      el.style.height = origHeight;
      el.style.maxHeight = origMaxH;

      const imgData = canvas.toDataURL('image/jpeg', 0.85);
      const imgW = canvas.width;
      const imgH = canvas.height;
      const pdfW = 210; // A4 mm
      const pdfH = 297;
      const ratio = pdfW / imgW;
      const scaledH = imgH * ratio;
      const pageH = pdfH - 20; // 10mm margin top+bottom
      const pages = Math.ceil(scaledH / pageH);

      const pdf = new jsPDF('p', 'mm', 'a4');
      for (let i = 0; i < pages; i++) {
        if (i > 0) pdf.addPage();
        pdf.addImage(imgData, 'JPEG', 0, -(i * pageH) + 10, pdfW, scaledH);
      }

      const name = (propResult || fetchedResult)?.suite_name || 'validation';
      const rid = (propResult || fetchedResult)?.run_id?.slice(0, 8) || 'report';
      const fileName = `${name}_${rid}.pdf`;

      // Use blob download for maximum compatibility
      const blob = pdf.output('blob');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('PDF export failed:', err);
      // Fallback to browser print dialog
      window.print();
    } finally {
      setExporting(false);
    }
  }, [propResult, fetchedResult]);

  const copyLink = useCallback(() => {
    const rid = (propResult || fetchedResult)?.run_id;
    if (rid) {
      navigator.clipboard.writeText(window.location.origin + '/results/' + rid);
      setCopied(true);
    }
  }, [propResult, fetchedResult]);

  const exportJson = useCallback(() => {
    const data = propResult || fetchedResult;
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.suite_name || 'validation'}_${data.run_id?.slice(0, 8) || 'report'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [propResult, fetchedResult]);

  useEffect(() => {
    if (!propResult && runId) {
      setLoading(true);
      getRunResult(runId)
        .then((r) => setFetchedResult(r.data))
        .catch((e) => setError(e.response?.data?.detail || 'Failed to load results'))
        .finally(() => setLoading(false));
    }
  }, [runId, propResult]);

  const result = propResult || fetchedResult;



  if (loading) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <CircularProgress sx={{ color: '#3171D6' }} />
      </Box>
    );
  }
  if (error) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 2 }}>
        <Typography sx={{ color: '#DC2626', fontWeight: 600 }}>{error}</Typography>
        <Button onClick={() => navigate('/')} variant="outlined">Back to Dashboard</Button>
      </Box>
    );
  }
  if (!result) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 2 }}>
        <Typography sx={{ color: '#64748B' }}>No result data available</Typography>
        <Button onClick={() => navigate('/')} variant="outlined">Back to Dashboard</Button>
      </Box>
    );
  }

  const summary = result.summary || {};
  const checks = result.checks || [];
  const timings = result.timings || [];
  const overallCfg = S[summary.overall_status] || S.Pass;
  const OverallIcon = overallCfg.icon;
  const score = Math.round(summary.quality_score ?? 100);

  // Sort: failed first, then errors, then passed
  const sortedChecks = [...checks].sort((a, b) => {
    const order = { Fail: 0, Error: 1, Warning: 2, Pass: 3 };
    return (order[a.status] ?? 4) - (order[b.status] ?? 4);
  });

  const filteredChecks = sortedChecks.filter((c) =>
    filter === 'all' ? true : filter === 'failed' ? (c.status === 'Fail' || c.status === 'Error') : c.status === 'Pass'
  );

  const failedCount = checks.filter(c => c.status === 'Fail' || c.status === 'Error').length;

  return (
    <Box ref={reportRef} sx={{ height: '100%', overflowY: 'auto' }}>
      {/* ── Top banner — overall status ─────────────────── */}
      <Box sx={{
        background: summary.overall_status === 'Pass'
          ? 'linear-gradient(135deg, #059669 0%, #10B981 100%)'
          : summary.overall_status === 'Fail'
          ? 'linear-gradient(135deg, #B91C1C 0%, #DC2626 100%)'
          : 'linear-gradient(135deg, #B45309 0%, #D97706 100%)',
        px: 4, py: 2.5,
        display: 'flex', alignItems: 'center', gap: 2.5,
        position: 'relative',
      }}>
        <IconButton onClick={() => navigate(-1)} size="small" sx={{ bgcolor: 'rgba(255,255,255,0.15)', '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' } }}>
          <ArrowBackRoundedIcon sx={{ color: '#fff', fontSize: 18 }} />
        </IconButton>

        <ScoreRing score={score} />

        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff', lineHeight: 1.2 }}>
            Validation {overallCfg.label === 'PASS' ? 'Passed' : overallCfg.label === 'FAIL' ? 'Failed' : overallCfg.label}
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.7)', mt: 0.25 }}>
            {result.suite_name || 'Ad-hoc'} · {result.run_id?.slice(0, 8)} · {summary.duration_s}s
          </Typography>
        </Box>

        {/* Action buttons */}
        <Box sx={{ display: 'flex', gap: 0.75 }}>
          <Tooltip title="Copy link">
            <IconButton onClick={copyLink} size="small" sx={{ bgcolor: 'rgba(255,255,255,0.15)', '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' } }}>
              <ContentCopyRoundedIcon sx={{ color: '#fff', fontSize: 16 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Export to PDF">
            <IconButton onClick={exportPdf} disabled={exporting} size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.15)', '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' } }}>
              {exporting
                ? <CircularProgress size={16} sx={{ color: '#fff' }} />
                : <PictureAsPdfRoundedIcon sx={{ color: '#fff', fontSize: 16 }} />}
            </IconButton>
          </Tooltip>
        </Box>

        {/* Summary pills */}
        <Box sx={{ display: 'flex', gap: 1 }}>
          <StatPill label="checks" value={summary.total} color="rgba(255,255,255,0.9)" />
          <StatPill label="passed" value={summary.passed} color="rgba(255,255,255,0.9)" />
          {summary.failed > 0 && <StatPill label="failed" value={summary.failed} color="rgba(255,255,255,0.9)" bold />}
          {summary.errors > 0 && <StatPill label="errors" value={summary.errors} color="rgba(255,255,255,0.9)" bold />}
        </Box>
      </Box>

      {/* ── Content ─────────────────────────────────────── */}
      <Box sx={{ px: 4, py: 3 }}>
        {/* Natural language summary + run metadata */}
        <Box sx={{
          display: 'flex', gap: 2, mb: 2.5, flexWrap: 'wrap',
        }}>
          {/* Summary box */}
          <Box sx={{
            flex: '1 1 300px', bgcolor: '#fff', borderRadius: '12px', p: 2,
            border: '1px solid rgba(15,23,42,0.06)',
            boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
          }}>
            <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', mb: 1 }}>
              Summary
            </Typography>
            <Typography sx={{ fontSize: '0.82rem', color: '#334155', lineHeight: 1.7 }}>
              {generateSummary(summary, checks)}
            </Typography>
          </Box>
          {/* Run metadata */}
          <Box sx={{
            flex: '0 0 220px', bgcolor: '#fff', borderRadius: '12px', p: 2,
            border: '1px solid rgba(15,23,42,0.06)',
            boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
          }}>
            <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', mb: 1 }}>
              Run Details
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
              {[
                { label: 'Suite', value: result.suite_name || 'Ad-hoc' },
                { label: 'Run ID', value: result.run_id?.slice(0, 12) || '—', mono: true },
                { label: 'Duration', value: summary.duration_s != null ? `${summary.duration_s}s` : '—' },
                { label: 'Timestamp', value: result.run_at ? new Date(result.run_at).toLocaleString() : '—' },
                ...(result.source_table ? [{ label: 'Source', value: result.source_table, mono: true }] : []),
                ...(result.target_table ? [{ label: 'Target', value: result.target_table, mono: true }] : []),
              ].map(item => (
                <Box key={item.label} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Typography sx={{ fontSize: '0.68rem', color: '#94A3B8', fontWeight: 500 }}>{item.label}</Typography>
                  <Typography sx={{
                    fontSize: '0.68rem', color: '#334155', fontWeight: 600,
                    fontFamily: item.mono ? '"JetBrains Mono", monospace' : 'inherit',
                    maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }} title={item.value}>{item.value}</Typography>
                </Box>
              ))}
            </Box>
          </Box>
        </Box>

        {/* Filter bar */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2.5 }}>
          <Typography sx={{ fontSize: '0.95rem', fontWeight: 800, color: '#0F172A' }}>
            Check Results
            {failedCount > 0 && (
              <Typography component="span" sx={{ fontSize: '0.75rem', fontWeight: 600, color: '#DC2626', ml: 1 }}>
                {failedCount} issue{failedCount !== 1 ? 's' : ''} found
              </Typography>
            )}
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {[
              { key: 'all', label: 'All', count: checks.length },
              { key: 'failed', label: 'Issues', count: failedCount },
              { key: 'passed', label: 'Passed', count: checks.filter(c => c.status === 'Pass').length },
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

        {/* Check cards — vertical stack */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {filteredChecks.map((check, i) => (
            <CheckCard
              key={i}
              check={check}
              defaultOpen={check.status === 'Fail' && check.details?.length > 0}
              timing={timings?.find(t => t.check_type === check.check_type)}
            />
          ))}
          {filteredChecks.length === 0 && (
            <Box sx={{ py: 8, textAlign: 'center' }}>
              <Typography sx={{ color: '#94A3B8' }}>No checks match this filter</Typography>
            </Box>
          )}
        </Box>
      </Box>
      <Snackbar open={copied} autoHideDuration={2000} onClose={() => setCopied(false)} message="Link copied to clipboard" />
    </Box>
  );
}
