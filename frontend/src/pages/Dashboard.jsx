import { useState, useEffect, useMemo } from 'react';
import {
  Box, Typography, Skeleton, Button, Chip, TextField,
  Table, TableBody, TableCell, TableHead, TableRow, Select, MenuItem,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import PlayCircleFilledRoundedIcon from '@mui/icons-material/PlayCircleFilledRounded';
import AssessmentRoundedIcon from '@mui/icons-material/AssessmentRounded';
import TrendingUpRoundedIcon from '@mui/icons-material/TrendingUpRounded';
import TrendingDownRoundedIcon from '@mui/icons-material/TrendingDownRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import CalendarTodayRoundedIcon from '@mui/icons-material/CalendarTodayRounded';
import FilterListRoundedIcon from '@mui/icons-material/FilterListRounded';
import { StatusChip, EmptyState } from '../components/Shared';
import { getHistory } from '../api';

/* ── tooltip style ───────────────────────────────────────── */
const TT = {
  background: '#0F172A',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 8,
  color: '#F1F5F9',
  fontSize: 11,
  boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
  padding: '6px 10px',
};

/* ── loading skeleton ────────────────────────────────────── */
function LoadingSkeleton() {
  return (
    <Box sx={{ height: '100%', overflowY: 'auto', p: 3 }}>
      <Box sx={{ display: 'flex', gap: 1.5, mb: 3 }}>
        {[1,2,3,4,5].map(i => <Skeleton key={i} variant="rounded" height={80} sx={{ flex: 1, borderRadius: 2.5 }} />)}
      </Box>
      <Box sx={{ display: 'flex', gap: 2, mb: 2.5 }}>
        <Skeleton variant="rounded" height={260} sx={{ flex: 1, borderRadius: 2.5 }} />
        <Skeleton variant="rounded" height={260} sx={{ flex: 1, borderRadius: 2.5 }} />
      </Box>
      <Skeleton variant="rounded" height={220} sx={{ borderRadius: 2.5 }} />
    </Box>
  );
}

/* ── stat card (compact) ─────────────────────────────────── */
function StatCard({ label, value, sub, color, icon: Icon, active }) {
  return (
    <Box sx={{
      flex: 1, bgcolor: '#fff', borderRadius: '14px', p: 2.5,
      border: active ? '1.5px solid ' + color + '33' : '1px solid rgba(15,23,42,0.06)',
      boxShadow: active ? '0 4px 16px ' + color + '12' : '0 1px 3px rgba(15,23,42,0.04)',
      transition: 'all 0.2s',
      position: 'relative', overflow: 'hidden',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Box sx={{
          width: 28, height: 28, borderRadius: '8px',
          bgcolor: color + '10', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Icon sx={{ fontSize: 15, color: color }} />
        </Box>
        <Typography sx={{
          fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          {label}
        </Typography>
      </Box>
      <Typography sx={{
        fontSize: '1.75rem', fontWeight: 800, color: active ? color : '#0F172A',
        lineHeight: 1, letterSpacing: '-0.03em',
        fontFamily: '"JetBrains Mono", monospace',
      }}>
        {value}
      </Typography>
      {sub && (
        <Typography sx={{ fontSize: '0.68rem', color: '#94A3B8', mt: 0.5 }}>
          {sub}
        </Typography>
      )}
    </Box>
  );
}

/* ── quality score ring ──────────────────────────────────── */
function ScoreRing({ score }) {
  const color = score >= 90 ? '#059669' : score >= 70 ? '#D97706' : '#DC2626';
  const label = score >= 90 ? 'Healthy' : score >= 70 ? 'Warning' : 'Critical';
  const circ = 2 * Math.PI * 32;
  return (
    <Box sx={{
      flex: 1, bgcolor: '#fff', borderRadius: '14px', p: 2.5,
      border: '1px solid rgba(15,23,42,0.06)',
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      display: 'flex', alignItems: 'center', gap: 2,
    }}>
      <Box sx={{ position: 'relative', flexShrink: 0 }}>
        <svg width={72} height={72} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx="36" cy="36" r="32" fill="none" stroke="rgba(15,23,42,0.05)" strokeWidth="6" />
          <circle cx="36" cy="36" r="32" fill="none" stroke={color} strokeWidth="6"
            strokeDasharray={(score / 100) * circ + ' ' + circ} strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 0.8s ease' }} />
        </svg>
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography sx={{ fontSize: '1.15rem', fontWeight: 800, color: color, fontFamily: '"JetBrains Mono", monospace' }}>
            {score}
          </Typography>
        </Box>
      </Box>
      <Box>
        <Typography sx={{ fontSize: '0.62rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', mb: 0.25 }}>
          Health Score
        </Typography>
        <Chip label={label} size="small" sx={{
          height: 20, fontSize: '0.6rem', fontWeight: 700,
          bgcolor: color + '12', color: color, border: '1px solid ' + color + '22',
        }} />
      </Box>
    </Box>
  );
}

/* ── Score Trend (quality % over time) ───────────────────── */
function ScoreTrendChart({ scoreTrend }) {
  if (!scoreTrend || scoreTrend.length < 2) return null;

  const latest = scoreTrend[scoreTrend.length - 1]?.quality_score || 0;
  const prev = scoreTrend.length > 1 ? scoreTrend[scoreTrend.length - 2]?.quality_score || 0 : latest;
  const delta = latest - prev;

  return (
    <Box sx={{
      bgcolor: '#fff', borderRadius: '14px', p: 2.5, flex: 1,
      border: '1px solid rgba(15,23,42,0.06)',
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      display: 'flex', flexDirection: 'column',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
        <Box>
          <Typography sx={{
            fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8',
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>
            Quality Score Trend
          </Typography>
          <Typography sx={{ fontSize: '0.6rem', color: '#CBD5E1', mt: 0.25 }}>
            Daily pass rate over time
          </Typography>
        </Box>
        {delta !== 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
            {delta > 0
              ? <TrendingUpRoundedIcon sx={{ fontSize: 14, color: '#059669' }} />
              : <TrendingDownRoundedIcon sx={{ fontSize: 14, color: '#DC2626' }} />
            }
            <Typography sx={{
              fontSize: '0.68rem', fontWeight: 700,
              color: delta > 0 ? '#059669' : '#DC2626',
            }}>
              {delta > 0 ? '+' : ''}{delta.toFixed(1)}%
            </Typography>
          </Box>
        )}
      </Box>
      <Box sx={{ flex: 1, minHeight: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={scoreTrend} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="gScore" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0D9488" stopOpacity={0.2} />
                <stop offset="100%" stopColor="#0D9488" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 0" stroke="rgba(148,163,184,0.06)" vertical={false} />
            <XAxis dataKey="day" tick={{ fill: '#94A3B8', fontSize: 10 }} axisLine={false} tickLine={false}
              tickFormatter={(v) => v ? v.slice(5) : v} />
            <YAxis domain={[0, 100]} tick={{ fill: '#94A3B8', fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={TT} formatter={(v) => [v + '%', 'Quality Score']} />
            <Area type="monotone" dataKey="quality_score" stroke="#0D9488" strokeWidth={2.5}
              fill="url(#gScore)" dot={false} activeDot={{ r: 4, fill: '#0D9488' }} name="Score" />
          </AreaChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}

/* ── trend chart (pass/fail stacked area) ────────────────── */
function TrendChart({ trend }) {
  const pivoted = useMemo(() => {
    const map = {};
    trend.forEach(t => {
      if (!map[t.day]) map[t.day] = { day: t.day, pass: 0, fail: 0, error: 0 };
      const s = (t.status || '').toLowerCase();
      if (s === 'pass') map[t.day].pass += t.count;
      else if (s === 'fail') map[t.day].fail += t.count;
      else map[t.day].error += t.count;
    });
    return Object.values(map).sort((a, b) => a.day.localeCompare(b.day));
  }, [trend]);

  if (pivoted.length === 0) return null;

  return (
    <Box sx={{
      bgcolor: '#fff', borderRadius: '14px', p: 2.5, flex: 1,
      border: '1px solid rgba(15,23,42,0.06)',
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      display: 'flex', flexDirection: 'column',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Typography sx={{
          fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8',
          textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          Daily Trend
        </Typography>
        <Box sx={{ display: 'flex', gap: 2 }}>
          {[
            { color: '#059669', label: 'Pass' },
            { color: '#DC2626', label: 'Fail' },
            { color: '#D97706', label: 'Error' },
          ].map(l => (
            <Box key={l.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 8, height: 3, borderRadius: 1, bgcolor: l.color }} />
              <Typography sx={{ fontSize: '0.6rem', color: '#94A3B8' }}>{l.label}</Typography>
            </Box>
          ))}
        </Box>
      </Box>
      <Box sx={{ flex: 1, minHeight: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={pivoted} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="gPass" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#059669" stopOpacity={0.2} />
                <stop offset="100%" stopColor="#059669" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gFail" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#DC2626" stopOpacity={0.2} />
                <stop offset="100%" stopColor="#DC2626" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 0" stroke="rgba(148,163,184,0.06)" vertical={false} />
            <XAxis dataKey="day" tick={{ fill: '#94A3B8', fontSize: 10 }} axisLine={false} tickLine={false}
              tickFormatter={(v) => v ? v.slice(5) : v} />
            <YAxis tick={{ fill: '#94A3B8', fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip contentStyle={TT} />
            <Area type="monotone" dataKey="pass" stackId="1" stroke="#059669" strokeWidth={2} fill="url(#gPass)" dot={false} />
            <Area type="monotone" dataKey="fail" stackId="1" stroke="#DC2626" strokeWidth={2} fill="url(#gFail)" dot={false} />
            <Area type="monotone" dataKey="error" stackId="1" stroke="#D97706" strokeWidth={1.5} fill="rgba(217,119,6,0.08)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}

/* ── main dashboard ──────────────────────────────────────── */
export default function Dashboard() {
  const [suite, setSuite] = useState('');
  const [days, setDays] = useState(30);
  const [statusFilter, setStatusFilter] = useState('all');
  const [checkTypeFilter, setCheckTypeFilter] = useState('all');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedBatches, setExpandedBatches] = useState({});
  const navigate = useNavigate();

  const toggleBatch = (batchId) => setExpandedBatches((prev) => ({ ...prev, [batchId]: !prev[batchId] }));

  useEffect(() => {
    setLoading(true);
    getHistory(suite, days)
      .then((r) => setData(r.data))
      .catch(() => setData({ results: [], trend: [], score_trend: [] }))
      .finally(() => setLoading(false));
  }, [suite, days]);

  const rawResults = data?.results || [];
  const trend = data?.trend || [];
  const scoreTrend = data?.score_trend || [];

  const checkTypes = useMemo(() => {
    const types = new Set(rawResults.map(r => r.check_type));
    return [...types].sort();
  }, [rawResults]);

  const runs = useMemo(() => {
    const filtered = checkTypeFilter === 'all' ? rawResults : rawResults.filter(r => r.check_type === checkTypeFilter);

    // First group by run_id (individual runs)
    const byRunId = {};
    filtered.forEach(row => {
      const id = row.run_id;
      if (!byRunId[id]) {
        byRunId[id] = {
          run_id: id, batch_id: row.batch_id || null, suite: row.suite,
          source: row.source,
          timestamp: row.timestamp, checks: [],
          passed: 0, failed: 0, errors: 0, duration_s: 0,
        };
      }
      byRunId[id].checks.push({ type: row.check_type, status: row.status, message: row.message });
      byRunId[id].duration_s += row.duration_s || 0;
      if (row.status === 'Pass') byRunId[id].passed++;
      else if (row.status === 'Fail') byRunId[id].failed++;
      else byRunId[id].errors++;
    });

    // Now merge runs that share a batch_id
    const batches = {};
    const standalone = [];
    Object.values(byRunId).forEach(run => {
      if (run.batch_id) {
        if (!batches[run.batch_id]) {
          batches[run.batch_id] = {
            run_id: run.batch_id, batch_id: run.batch_id, suite: run.suite,
            source: run.source,
            timestamp: run.timestamp, checks: [],
            passed: 0, failed: 0, errors: 0, duration_s: 0,
            pair_count: 0, is_batch: true, children: [],
          };
        }
        const b = batches[run.batch_id];
        b.pair_count++;
        b.children.push(run);
        b.checks.push(...run.checks);
        b.duration_s += run.duration_s;
        b.passed += run.passed;
        b.failed += run.failed;
        b.errors += run.errors;
        // Use earliest timestamp
        if (run.timestamp < b.timestamp) b.timestamp = run.timestamp;
      } else {
        standalone.push(run);
      }
    });

    const grouped = [...Object.values(batches), ...standalone].map(run => {
      const total = run.checks.length;
      const status = run.errors > 0 ? 'Error' : run.failed > 0 ? 'Fail' : 'Pass';
      const quality_score = total > 0 ? Math.round((run.passed / total) * 100) : null;
      return { ...run, total_checks: total, status, quality_score };
    });
    // Sort by timestamp descending
    grouped.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
    if (statusFilter === 'all') return grouped;
    return grouped.filter(r => r.status === statusFilter);
  }, [rawResults, statusFilter, checkTypeFilter]);

  const totalChecks = rawResults.length;
  const uniqueRuns = new Set(rawResults.map(r => r.run_id)).size;

  // Test-case-level stats: group by run_id and determine overall status per test case
  const tcStats = useMemo(() => {
    const byRun = {};
    rawResults.forEach(r => {
      if (!byRun[r.run_id]) byRun[r.run_id] = { hasError: false, hasFail: false };
      if (r.status === 'Error') byRun[r.run_id].hasError = true;
      else if (r.status === 'Fail') byRun[r.run_id].hasFail = true;
    });
    let passed = 0, failed = 0, errored = 0;
    Object.values(byRun).forEach(s => {
      if (s.hasError) errored++;
      else if (s.hasFail) failed++;
      else passed++;
    });
    return { passed, failed, errored };
  }, [rawResults]);

  const passed = tcStats.passed;
  const failed = tcStats.failed;
  const errored = tcStats.errored;
  const passRate = uniqueRuns > 0 ? Math.round((passed / uniqueRuns) * 100) : 100;

  if (loading) return <LoadingSkeleton />;

  if (rawResults.length === 0) {
    return (
      <Box sx={{ height: '100%', overflowY: 'auto', p: 3 }}>
        <Box sx={{ mb: 3 }}>
          <Typography sx={{ fontSize: '1.5rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.03em' }}>
            Data Quality Dashboard
          </Typography>
          <Typography sx={{ fontSize: '0.8rem', color: '#64748B', mt: 0.5 }}>
            Run your first validation to start tracking quality
          </Typography>
        </Box>
        <EmptyState
          icon={AssessmentRoundedIcon}
          title="No validation results yet"
          subtitle="Run a test suite to populate your dashboard with metrics, trends, and insights."
          action={
            <Button variant="contained" startIcon={<PlayCircleFilledRoundedIcon />} onClick={() => navigate('/suite')}
              sx={{ px: 3, fontWeight: 700, background: 'linear-gradient(135deg,#1D55B0,#3171D6)', boxShadow: '0 4px 14px rgba(49,113,214,0.3)' }}>
              Run a Suite
            </Button>
          }
        />
      </Box>
    );
  }

  return (
    <Box sx={{ height: '100%', overflowY: 'auto', p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2.5 }}>
        <Box>
          <Typography sx={{ fontSize: '1.35rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.03em' }}>
            Data Quality Dashboard
          </Typography>
          <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8', mt: 0.25 }}>
            {days}-day window &middot; {uniqueRuns} test case{uniqueRuns !== 1 ? 's' : ''} &middot; {totalChecks} check{totalChecks !== 1 ? 's' : ''}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button size="small" variant="contained" startIcon={<PlayCircleFilledRoundedIcon sx={{ fontSize: 14 }} />}
            onClick={() => navigate('/suite')}
            sx={{ fontSize: '0.68rem', fontWeight: 600, background: 'linear-gradient(135deg,#1D55B0,#3171D6)', textTransform: 'none', boxShadow: '0 2px 8px rgba(49,113,214,0.25)' }}>
            Run Suite
          </Button>
        </Box>
      </Box>

      {/* Row 1: Stats */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2.5 }}>
        <StatCard label="Test Cases" value={uniqueRuns} sub={totalChecks + ' checks'} color="#3171D6" icon={AssessmentRoundedIcon} />
        <StatCard label="Passed" value={passed} sub={passRate + '% pass rate'} color="#059669" icon={CheckCircleRoundedIcon} active={passed > 0} />
        <StatCard label="Failed" value={failed} color="#DC2626" icon={CancelRoundedIcon} active={failed > 0} />
        <StatCard label="Errors" value={errored} color="#D97706" icon={ErrorOutlineRoundedIcon} active={errored > 0} />
        <ScoreRing score={passRate} />
      </Box>

      {/* Row 2: Score Trend + Daily Trend */}
      <Box sx={{ display: 'flex', gap: 1.5, mb: 2.5 }}>
        <ScoreTrendChart scoreTrend={scoreTrend} />
        <TrendChart trend={trend} />
      </Box>

      {/* Row 3: Filter bar */}
      <Box sx={{
        bgcolor: '#fff', borderRadius: '14px', p: 2, mb: 2.5,
        display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap',
        border: '1px solid rgba(15,23,42,0.06)',
        boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      }}>
        <SearchRoundedIcon sx={{ color: '#CBD5E1', fontSize: 18, flexShrink: 0 }} />
        <TextField
          variant="standard" placeholder="Filter by suite name…" value={suite}
          onChange={(e) => setSuite(e.target.value)}
          InputProps={{ disableUnderline: true, sx: { fontSize: '0.875rem', color: '#374151' } }}
          sx={{ flex: 1, minWidth: 120 }}
        />
        <Box sx={{ display: 'flex', gap: 0.5, flexShrink: 0 }}>
          <FilterListRoundedIcon sx={{ color: '#CBD5E1', fontSize: 15, mr: 0.25, alignSelf: 'center' }} />
          {[{ key: 'all', label: 'All' }, { key: 'Pass', label: 'Pass' }, { key: 'Fail', label: 'Fail' }, { key: 'Error', label: 'Error' }].map(f => (
            <Box key={f.key} onClick={() => setStatusFilter(f.key)} sx={{
              px: 1.25, py: 0.4, borderRadius: '7px', cursor: 'pointer',
              bgcolor: statusFilter === f.key ? (f.key === 'Pass' ? 'rgba(5,150,105,0.1)' : f.key === 'Fail' ? 'rgba(220,38,38,0.1)' : f.key === 'Error' ? 'rgba(245,158,11,0.1)' : 'rgba(49,113,214,0.1)') : 'transparent',
              border: '1px solid ' + (statusFilter === f.key ? (f.key === 'Pass' ? 'rgba(5,150,105,0.25)' : f.key === 'Fail' ? 'rgba(220,38,38,0.25)' : f.key === 'Error' ? 'rgba(245,158,11,0.25)' : 'rgba(49,113,214,0.25)') : 'rgba(15,23,42,0.06)'),
              transition: 'all 0.15s',
            }}>
              <Typography sx={{ fontSize: '0.72rem', fontWeight: statusFilter === f.key ? 700 : 500, color: statusFilter === f.key ? (f.key === 'Pass' ? '#059669' : f.key === 'Fail' ? '#DC2626' : f.key === 'Error' ? '#D97706' : '#3171D6') : '#64748B' }}>
                {f.label}
              </Typography>
            </Box>
          ))}
        </Box>
        {checkTypes.length > 1 && (
          <Select
            size="small" value={checkTypeFilter}
            onChange={(e) => setCheckTypeFilter(e.target.value)}
            sx={{ fontSize: '0.75rem', height: 28, minWidth: 100, '& .MuiSelect-select': { py: 0.5 } }}
          >
            <MenuItem value="all" sx={{ fontSize: '0.75rem' }}>All Types</MenuItem>
            {checkTypes.map(t => <MenuItem key={t} value={t} sx={{ fontSize: '0.75rem' }}>{t}</MenuItem>)}
          </Select>
        )}
        <Box sx={{ display: 'flex', gap: 0.75, flexShrink: 0 }}>
          <CalendarTodayRoundedIcon sx={{ color: '#CBD5E1', fontSize: 15, mr: 0.5, alignSelf: 'center' }} />
          {[7, 14, 30, 90].map((d) => (
            <Box key={d} onClick={() => setDays(d)} sx={{
              px: 1.5, py: 0.5, borderRadius: '8px', cursor: 'pointer',
              bgcolor: days === d ? 'rgba(49,113,214,0.1)' : 'transparent',
              border: '1px solid ' + (days === d ? 'rgba(49,113,214,0.25)' : 'rgba(15,23,42,0.08)'),
              transition: 'all 0.15s',
              '&:hover': { bgcolor: days === d ? 'rgba(49,113,214,0.12)' : 'rgba(15,23,42,0.03)' },
            }}>
              <Typography sx={{ fontSize: '0.78rem', fontWeight: days === d ? 700 : 500, color: days === d ? '#3171D6' : '#64748B' }}>
                {d}d
              </Typography>
            </Box>
          ))}
        </Box>
      </Box>

      {/* Row 4: Results table */}
      <Box sx={{
        bgcolor: '#fff', borderRadius: '16px', overflow: 'hidden',
        border: '1px solid rgba(15,23,42,0.06)',
        boxShadow: '0 1px 3px rgba(15,23,42,0.04), 0 6px 20px rgba(15,23,42,0.05)',
      }}>
        <Box sx={{ px: 3, py: 2.25, borderBottom: '1px solid rgba(15,23,42,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#0F172A' }}>
            All Results
          </Typography>
          <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8' }}>{runs.length} run{runs.length !== 1 ? 's' : ''}</Typography>
        </Box>
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: '#FAFBFC' }}>
                {['', 'Suite / Source', 'Checks', 'Status', 'Score', 'Duration', 'Run At'].map((h) => (
                  <TableCell key={h || '_expand'} sx={{ fontSize: '0.65rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em', py: 1.5, borderBottom: '1px solid rgba(15,23,42,0.06)', ...(h === '' ? { width: 32, px: 0.5 } : {}) }}>
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.slice(0, 50).flatMap((r, i) => {
                const isExpanded = r.is_batch && expandedBatches[r.batch_id];
                const mainRow = (
                <TableRow key={r.run_id || i}
                  onClick={() => {
                    if (r.is_batch && r.batch_id) toggleBatch(r.batch_id);
                    else if (r.run_id) navigate('/results/' + r.run_id);
                  }}
                  sx={{
                    cursor: 'pointer',
                    '&:hover': { bgcolor: 'rgba(49,113,214,0.04)' },
                    '& td': { borderBottom: isExpanded ? 'none' : '1px solid rgba(15,23,42,0.04)', py: 1.5 },
                    ...(isExpanded ? { bgcolor: 'rgba(49,113,214,0.02)' } : {}),
                  }}>
                  <TableCell sx={{ px: 0.5, width: 32 }}>
                    {r.is_batch && (
                      <ExpandMoreRoundedIcon sx={{
                        fontSize: 18, color: '#94A3B8',
                        transition: 'transform 0.2s',
                        transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                      }} />
                    )}
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color: '#0F172A', fontFamily: 'monospace' }} noWrap>
                        {r.suite || r.source || '—'}
                      </Typography>
                      {r.is_batch && (
                        <Chip label={`${r.pair_count} test case${r.pair_count !== 1 ? 's' : ''}`} size="small" sx={{
                          height: 18, fontSize: '0.58rem', fontWeight: 700,
                          bgcolor: 'rgba(49,113,214,0.08)', color: '#3171D6',
                          border: '1px solid rgba(49,113,214,0.2)',
                        }} />
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {r.is_batch ? (
                        <>
                          <Box sx={{ px: 0.75, py: 0.25, borderRadius: '6px', fontSize: '0.62rem', fontWeight: 600,
                            bgcolor: 'rgba(5,150,105,0.08)', color: '#059669' }}>
                            {r.passed} pass
                          </Box>
                          {r.failed > 0 && (
                            <Box sx={{ px: 0.75, py: 0.25, borderRadius: '6px', fontSize: '0.62rem', fontWeight: 600,
                              bgcolor: 'rgba(220,38,38,0.08)', color: '#DC2626' }}>
                              {r.failed} fail
                            </Box>
                          )}
                          {r.errors > 0 && (
                            <Box sx={{ px: 0.75, py: 0.25, borderRadius: '6px', fontSize: '0.62rem', fontWeight: 600,
                              bgcolor: 'rgba(245,158,11,0.08)', color: '#D97706' }}>
                              {r.errors} err
                            </Box>
                          )}
                        </>
                      ) : r.checks?.map((c, ci) => (
                        <Box key={ci} sx={{ px: 0.75, py: 0.25, borderRadius: '6px', fontSize: '0.62rem', fontWeight: 600,
                          bgcolor: c.status === 'Pass' ? 'rgba(5,150,105,0.08)' : c.status === 'Fail' ? 'rgba(220,38,38,0.08)' : 'rgba(245,158,11,0.08)',
                          color: c.status === 'Pass' ? '#059669' : c.status === 'Fail' ? '#DC2626' : '#D97706' }}>
                          {c.type}
                        </Box>
                      ))}
                    </Box>
                  </TableCell>
                  <TableCell><StatusChip status={r.status} /></TableCell>
                  <TableCell>
                    {r.quality_score != null && (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Box sx={{ width: 48, height: 4, bgcolor: 'rgba(15,23,42,0.06)', borderRadius: 2, overflow: 'hidden' }}>
                          <Box sx={{ height: '100%', width: r.quality_score + '%', bgcolor: r.quality_score >= 90 ? '#059669' : r.quality_score >= 70 ? '#D97706' : '#DC2626', borderRadius: 2 }} />
                        </Box>
                        <Typography sx={{ fontSize: '0.72rem', fontWeight: 700, color: '#374151' }}>{Math.round(r.quality_score)}</Typography>
                      </Box>
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography sx={{ fontSize: '0.72rem', color: '#64748B', fontFamily: '"JetBrains Mono", monospace' }}>
                      {r.duration_s ? (r.duration_s >= 1 ? r.duration_s.toFixed(1) + 's' : Math.round(r.duration_s * 1000) + 'ms') : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8' }}>
                        {r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}
                      </Typography>
                      {r.is_batch && (
                        <OpenInNewRoundedIcon
                          onClick={(e) => { e.stopPropagation(); navigate('/results/batch/' + r.batch_id); }}
                          sx={{ fontSize: 14, color: '#94A3B8', '&:hover': { color: '#3171D6' }, cursor: 'pointer' }}
                          titleAccess="View consolidated report"
                        />
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
                );
                if (!isExpanded || !r.children) return [mainRow];
                const childRows = r.children.map((child, ci) => {
                  const childTotal = child.checks.length;
                  const childStatus = child.errors > 0 ? 'Error' : child.failed > 0 ? 'Fail' : 'Pass';
                  const childScore = childTotal > 0 ? Math.round((child.passed / childTotal) * 100) : null;
                  const srcLabel = (child.source || '').split('/').pop() || child.source || '—';
                  return (
                    <TableRow key={`${r.batch_id}-${child.run_id}`}
                      onClick={(e) => { e.stopPropagation(); navigate('/results/' + child.run_id); }}
                      sx={{
                        cursor: 'pointer',
                        bgcolor: 'rgba(49,113,214,0.015)',
                        '&:hover': { bgcolor: 'rgba(49,113,214,0.05)' },
                        '& td': { borderBottom: ci === r.children.length - 1 ? '1px solid rgba(15,23,42,0.06)' : '1px solid rgba(15,23,42,0.03)', py: 1.25 },
                      }}>
                      <TableCell sx={{ px: 0.5, width: 32 }}>
                        <Box sx={{ width: 16, ml: 'auto', mr: 'auto', borderLeft: '2px solid rgba(49,113,214,0.15)', height: 20 }} />
                      </TableCell>
                      <TableCell>
                        <Typography sx={{ fontSize: '0.72rem', color: '#475569', fontFamily: 'monospace' }} noWrap>
                          {srcLabel}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                          {child.checks.map((c, cci) => (
                            <Box key={cci} sx={{ px: 0.75, py: 0.25, borderRadius: '6px', fontSize: '0.58rem', fontWeight: 600,
                              bgcolor: c.status === 'Pass' ? 'rgba(5,150,105,0.08)' : c.status === 'Fail' ? 'rgba(220,38,38,0.08)' : 'rgba(245,158,11,0.08)',
                              color: c.status === 'Pass' ? '#059669' : c.status === 'Fail' ? '#DC2626' : '#D97706' }}>
                              {c.type}
                            </Box>
                          ))}
                        </Box>
                      </TableCell>
                      <TableCell><StatusChip status={childStatus} /></TableCell>
                      <TableCell>
                        {childScore != null && (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Box sx={{ width: 48, height: 4, bgcolor: 'rgba(15,23,42,0.06)', borderRadius: 2, overflow: 'hidden' }}>
                              <Box sx={{ height: '100%', width: childScore + '%', bgcolor: childScore >= 90 ? '#059669' : childScore >= 70 ? '#D97706' : '#DC2626', borderRadius: 2 }} />
                            </Box>
                            <Typography sx={{ fontSize: '0.72rem', fontWeight: 700, color: '#374151' }}>{childScore}</Typography>
                          </Box>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography sx={{ fontSize: '0.72rem', color: '#64748B', fontFamily: '"JetBrains Mono", monospace' }}>
                          {child.duration_s ? (child.duration_s >= 1 ? child.duration_s.toFixed(1) + 's' : Math.round(child.duration_s * 1000) + 'ms') : '—'}
                        </Typography>
                      </TableCell>
                      <TableCell />
                    </TableRow>
                  );
                });
                return [mainRow, ...childRows];
              })}
            </TableBody>
          </Table>
        </Box>
      </Box>
    </Box>
  );
}
