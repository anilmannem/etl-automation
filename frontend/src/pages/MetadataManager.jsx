import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box, Typography, Button, TextField, Select, MenuItem,
  FormControl, InputLabel, Alert, IconButton, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, CircularProgress, Tooltip, Switch,
  FormControlLabel, LinearProgress, Paper,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import DeleteRoundedIcon from '@mui/icons-material/DeleteRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import StopCircleRoundedIcon from '@mui/icons-material/StopCircleRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ErrorRoundedIcon from '@mui/icons-material/ErrorRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import { EmptyState } from '../components/Shared';
import {
  listMetadata, createMetadata, updateMetadata, deleteMetadata,
  bulkImportMetadata, runFromMetadata, getBatchProgress, listConnections,
} from '../api';

const EMPTY_ENTRY = {
  group_name: 'default',
  source_connection: '',
  source_table: '',
  target_connection: '',
  target_table: '',
  join_keys: '',
  check_types: 'row_count,data',
  strategy: 'auto',
  priority: 50,
  tolerance: 0,
  where_clause: '',
  ignore_columns: 'DL_INSERT_TS,DL_UPDATE_TS',
  timestamp_column: 'DL_UPDATE_TS',
  schedule: 'daily',
  active: true,
  tags: '',
  notes: '',
};

const STRATEGIES = ['auto', 'minus', 'hash', 'full', 'sample'];
const CHECK_TYPES = ['row_count', 'data', 'schema', 'aggregate', 'null_check', 'duplicate_check'];

function StatsBar({ stats }) {
  if (!stats) return null;
  return (
    <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
      {[
        { label: 'Total', value: stats.total, color: '#3B82F6' },
        { label: 'Active', value: stats.active, color: '#10B981' },
        { label: 'Groups', value: stats.groups, color: '#8B5CF6' },
        { label: 'Sources', value: stats.source_connections, color: '#F59E0B' },
        { label: 'Targets', value: stats.target_connections, color: '#EC4899' },
      ].map((s) => (
        <Paper key={s.label} elevation={0} sx={{
          px: 2, py: 1, borderRadius: 2, bgcolor: '#F8FAFC',
          border: '1px solid #E2E8F0', display: 'flex', alignItems: 'center', gap: 1,
        }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: s.color }} />
          <Typography variant="caption" sx={{ color: '#64748B' }}>{s.label}</Typography>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{s.value ?? 0}</Typography>
        </Paper>
      ))}
    </Box>
  );
}

function MetadataRow({ entry, onEdit, onDelete, onRun }) {
  return (
    <Box sx={{
      display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.5,
      borderBottom: '1px solid #F1F5F9',
      '&:hover': { bgcolor: '#F8FAFC' },
      opacity: entry.active ? 1 : 0.5,
    }}>
      <StorageRoundedIcon sx={{ fontSize: 18, color: '#94A3B8' }} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {entry.source_table} → {entry.target_table}
        </Typography>
        <Typography variant="caption" sx={{ color: '#64748B' }}>
          {entry.source_connection} → {entry.target_connection}
          {entry.group_name && entry.group_name !== 'default' && ` • ${entry.group_name}`}
        </Typography>
      </Box>
      <Chip label={entry.strategy} size="small" sx={{ fontSize: 11, height: 22 }} />
      <Chip label={`P${entry.priority}`} size="small" variant="outlined" sx={{ fontSize: 11, height: 22 }} />
      {entry.tags && (
        <Chip label={entry.tags.split(',')[0]} size="small" sx={{ fontSize: 10, height: 20, bgcolor: '#EDE9FE' }} />
      )}
      <Tooltip title="Run Validation"><IconButton size="small" onClick={() => onRun(entry)}><PlayArrowRoundedIcon fontSize="small" sx={{ color: '#10B981' }} /></IconButton></Tooltip>
      <Tooltip title="Edit"><IconButton size="small" onClick={() => onEdit(entry)}><EditRoundedIcon fontSize="small" /></IconButton></Tooltip>
      <Tooltip title="Delete"><IconButton size="small" onClick={() => onDelete(entry)}><DeleteRoundedIcon fontSize="small" sx={{ color: '#DC2626' }} /></IconButton></Tooltip>
    </Box>
  );
}

function BatchProgressPanel({ batchId, onComplete }) {
  const [progress, setProgress] = useState(null);
  const [details, setDetails] = useState([]);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!batchId) return;

    const poll = async () => {
      try {
        const res = await getBatchProgress(batchId);
        setProgress(res.data.progress);
        setDetails(res.data.details || []);

        // Check if done
        if (res.data.progress?.pct_done >= 100) {
          clearInterval(intervalRef.current);
          onComplete?.(res.data.progress);
        }
      } catch (e) {
        // Batch might have expired — stop polling
        if (e.response?.status === 404) {
          clearInterval(intervalRef.current);
        }
      }
    };

    poll(); // immediate first poll
    intervalRef.current = setInterval(poll, 2000);

    return () => clearInterval(intervalRef.current);
  }, [batchId]);

  if (!progress) return <LinearProgress sx={{ mb: 2 }} />;

  const isComplete = progress.pct_done >= 100;
  const hasFailed = progress.failed > 0 || progress.errors > 0;

  return (
    <Paper elevation={0} sx={{
      mb: 2, borderRadius: 2, overflow: 'hidden',
      border: '1px solid',
      borderColor: isComplete ? (hasFailed ? '#FECACA' : '#BBF7D0') : '#BFDBFE',
      bgcolor: isComplete ? (hasFailed ? '#FEF2F2' : '#F0FDF4') : '#EFF6FF',
    }}>
      {/* Progress Header */}
      <Box sx={{ px: 2.5, pt: 2, pb: 1.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {isComplete ? (
              hasFailed ? <ErrorRoundedIcon sx={{ fontSize: 18, color: '#DC2626' }} />
                        : <CheckCircleRoundedIcon sx={{ fontSize: 18, color: '#059669' }} />
            ) : (
              <CircularProgress size={16} thickness={5} />
            )}
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              {isComplete ? 'Batch Complete' : 'Executing Validations…'}
            </Typography>
          </Box>
          <Typography variant="caption" sx={{ color: '#64748B', fontFamily: 'monospace' }}>
            {batchId}
          </Typography>
        </Box>

        {/* Progress bar */}
        {!isComplete && (
          <Box sx={{ mb: 1.5 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" sx={{ fontWeight: 600 }}>
                {progress.completed} / {progress.total} tables
              </Typography>
              <Typography variant="caption" sx={{ fontWeight: 600, color: '#3B82F6' }}>
                {progress.pct_done}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={progress.pct_done}
              sx={{
                height: 8, borderRadius: 4,
                bgcolor: '#DBEAFE',
                '& .MuiLinearProgress-bar': {
                  borderRadius: 4,
                  bgcolor: hasFailed ? '#F59E0B' : '#3B82F6',
                },
              }}
            />
          </Box>
        )}

        {/* Metrics row */}
        <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap', mt: 1 }}>
          {!isComplete && progress.running > 0 && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#3B82F6', animation: 'pulse 1.5s infinite' }} />
              <Typography variant="caption" sx={{ fontWeight: 600 }}>{progress.running} running</Typography>
            </Box>
          )}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#10B981' }} />
            <Typography variant="caption" sx={{ fontWeight: 600 }}>{progress.passed} passed</Typography>
          </Box>
          {progress.failed > 0 && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#DC2626' }} />
              <Typography variant="caption" sx={{ fontWeight: 600, color: '#DC2626' }}>{progress.failed} failed</Typography>
            </Box>
          )}
          {progress.errors > 0 && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#9333EA' }} />
              <Typography variant="caption" sx={{ fontWeight: 600, color: '#9333EA' }}>{progress.errors} errors</Typography>
            </Box>
          )}
          {!isComplete && progress.pending > 0 && (
            <Typography variant="caption" sx={{ color: '#94A3B8' }}>{progress.pending} pending</Typography>
          )}
          <Typography variant="caption" sx={{ color: '#64748B', ml: 'auto' }}>
            {progress.tables_per_min} tables/min • {progress.elapsed_s}s elapsed
            {!isComplete && progress.est_remaining_s > 0 && ` • ~${Math.round(progress.est_remaining_s)}s remaining`}
          </Typography>
        </Box>
      </Box>

      {/* Failed tables detail (show only failures/errors) */}
      {details.filter(d => d.status === 'fail' || d.status === 'error').length > 0 && (
        <Box sx={{ borderTop: '1px solid', borderColor: hasFailed ? '#FECACA' : '#E2E8F0', px: 2.5, py: 1.5, maxHeight: 160, overflow: 'auto' }}>
          <Typography variant="caption" sx={{ fontWeight: 700, color: '#DC2626', display: 'block', mb: 0.5 }}>
            Failed Tables
          </Typography>
          {details.filter(d => d.status === 'fail' || d.status === 'error').slice(0, 10).map((d, i) => (
            <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.25 }}>
              <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{d.table}</Typography>
              <Typography variant="caption" sx={{ color: '#64748B', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {d.message}
              </Typography>
            </Box>
          ))}
        </Box>
      )}
    </Paper>
  );
}

export default function MetadataManager() {
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const [groups, setGroups] = useState([]);
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editEntry, setEditEntry] = useState(null);
  const [form, setForm] = useState(EMPTY_ENTRY);
  const [filterGroup, setFilterGroup] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [running, setRunning] = useState(false);
  const [activeBatchId, setActiveBatchId] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const fileInputRef = useRef(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [metaRes, connRes] = await Promise.all([
        listMetadata(filterGroup, !showInactive),
        listConnections(),
      ]);
      setEntries(metaRes.data.entries || []);
      setStats(metaRes.data.stats);
      setGroups(metaRes.data.groups || []);
      setConnections(connRes.data || []);
      setError('');
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load metadata');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [filterGroup, showInactive]);

  const openCreate = () => {
    setEditEntry(null);
    setForm(EMPTY_ENTRY);
    setDialogOpen(true);
  };

  const openEdit = (entry) => {
    setEditEntry(entry);
    setForm({ ...entry, active: Boolean(entry.active) });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    try {
      if (editEntry) {
        await updateMetadata(editEntry.id, form);
        setSuccess('Entry updated');
      } else {
        await createMetadata(form);
        setSuccess('Entry created');
      }
      setDialogOpen(false);
      fetchData();
    } catch (e) {
      setError(e.response?.data?.detail || 'Save failed');
    }
  };

  const handleDelete = async (entry) => {
    if (!confirm(`Delete "${entry.source_table} → ${entry.target_table}"?`)) return;
    try {
      await deleteMetadata(entry.id);
      setSuccess('Entry deleted');
      fetchData();
    } catch (e) {
      setError(e.response?.data?.detail || 'Delete failed');
    }
  };

  const handleRunSingle = async (entry) => {
    setRunning(true);
    setRunResult(null);
    setActiveBatchId(null);
    try {
      const res = await runFromMetadata({ ids: [entry.id], max_workers: 1 });
      setActiveBatchId(res.data.batch_id);
    } catch (e) {
      setError(e.response?.data?.detail || 'Run failed');
      setRunning(false);
    }
  };

  const handleRunGroup = async () => {
    setRunning(true);
    setRunResult(null);
    setActiveBatchId(null);
    try {
      const res = await runFromMetadata({
        group_name: filterGroup || '',
        max_workers: 20,
        parallel: true,
      });
      setActiveBatchId(res.data.batch_id);
    } catch (e) {
      setError(e.response?.data?.detail || 'Batch run failed');
      setRunning(false);
    }
  };

  const handleBatchComplete = (finalProgress) => {
    setRunning(false);
    setRunResult(finalProgress);
    setSuccess(`Batch complete: ${finalProgress.passed}/${finalProgress.total} passed • ${finalProgress.tables_per_min} tables/min`);
  };

  const handleFileImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      let rows;
      if (file.name.endsWith('.json')) {
        rows = JSON.parse(text);
      } else {
        // CSV parse (simple — header row + comma separated)
        const lines = text.trim().split('\n');
        const headers = lines[0].split(',').map(h => h.trim());
        rows = lines.slice(1).map(line => {
          const vals = line.split(',').map(v => v.trim());
          const obj = {};
          headers.forEach((h, i) => { obj[h] = vals[i] || ''; });
          return obj;
        });
      }
      const res = await bulkImportMetadata(rows);
      setSuccess(`Imported ${res.data.count} of ${res.data.total_submitted} entries`);
      setImportDialogOpen(false);
      fetchData();
    } catch (err) {
      setError('Import failed: ' + (err.response?.data?.detail || err.message));
    }
    // Reset file input
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <Box sx={{ height: '100%', overflow: 'auto', p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>Validation Metadata</Typography>
          <Typography variant="body2" sx={{ color: '#64748B' }}>
            Centralized validation registry — define, organize, and execute table validations at scale
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" startIcon={<UploadFileRoundedIcon />} onClick={() => setImportDialogOpen(true)}>
            Import
          </Button>
          <Button variant="outlined" color="success" startIcon={running ? <CircularProgress size={16} /> : <PlayArrowRoundedIcon />}
            onClick={handleRunGroup} disabled={running}>
            {running ? 'Running…' : `Run ${filterGroup || 'All'}`}
          </Button>
          <Button variant="contained" startIcon={<AddRoundedIcon />} onClick={openCreate}>
            Add Entry
          </Button>
        </Box>
      </Box>

      {/* Alerts */}
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" onClose={() => setSuccess('')} sx={{ mb: 2 }}>{success}</Alert>}

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Filters */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Group Filter</InputLabel>
          <Select value={filterGroup} label="Group Filter" onChange={(e) => setFilterGroup(e.target.value)}>
            <MenuItem value="">All Groups</MenuItem>
            {groups.map(g => <MenuItem key={g} value={g}>{g}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControlLabel
          control={<Switch checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} size="small" />}
          label="Show Inactive"
        />
        <Typography variant="caption" sx={{ color: '#94A3B8', ml: 'auto' }}>
          {entries.length} entries
        </Typography>
      </Box>

      {/* Live Batch Progress Panel */}
      {activeBatchId && (
        <BatchProgressPanel batchId={activeBatchId} onComplete={handleBatchComplete} />
      )}

      {/* Table List */}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress /></Box>
      ) : entries.length === 0 ? (
        <EmptyState
          icon={StorageRoundedIcon}
          title="No metadata entries"
          subtitle="Add validation entries or import from CSV/JSON"
        />
      ) : (
        <Paper elevation={0} sx={{ border: '1px solid #E2E8F0', borderRadius: 2, overflow: 'hidden' }}>
          {/* Header row */}
          <Box sx={{ display: 'flex', px: 2, py: 1, bgcolor: '#F8FAFC', borderBottom: '1px solid #E2E8F0' }}>
            <Typography variant="caption" sx={{ flex: 1, fontWeight: 600, color: '#475569' }}>Table Pair</Typography>
            <Typography variant="caption" sx={{ width: 80, fontWeight: 600, color: '#475569' }}>Strategy</Typography>
            <Typography variant="caption" sx={{ width: 60, fontWeight: 600, color: '#475569' }}>Priority</Typography>
            <Typography variant="caption" sx={{ width: 140, fontWeight: 600, color: '#475569', textAlign: 'right' }}>Actions</Typography>
          </Box>
          {entries.map((entry) => (
            <MetadataRow
              key={entry.id}
              entry={entry}
              onEdit={openEdit}
              onDelete={handleDelete}
              onRun={handleRunSingle}
            />
          ))}
        </Paper>
      )}

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth
        slotProps={{ paper: { sx: { borderRadius: 3, maxHeight: '90vh' } } }}>
        <DialogTitle sx={{ pb: 1, fontWeight: 700 }}>
          {editEntry ? 'Edit Validation Entry' : 'Add Validation Entry'}
        </DialogTitle>
        <DialogContent sx={{ pt: '8px !important' }}>
          {/* Section: General */}
          <Typography variant="overline" sx={{ color: '#8B5CF6', fontWeight: 700, letterSpacing: 1.2, display: 'block', mb: 1 }}>
            General
          </Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 2, mb: 3 }}>
            <Box sx={{ gridColumn: 'span 2' }}>
              <TextField fullWidth label="Group Name" size="small" value={form.group_name}
                onChange={(e) => setForm({ ...form, group_name: e.target.value })} />
            </Box>
            <FormControl fullWidth size="small">
              <InputLabel>Strategy</InputLabel>
              <Select value={form.strategy} label="Strategy" onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
                {STRATEGIES.map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </Select>
            </FormControl>
          </Box>

          {/* Section: Source & Target */}
          <Typography variant="overline" sx={{ color: '#0EA5E9', fontWeight: 700, letterSpacing: 1.2, display: 'block', mb: 1 }}>
            Source & Target
          </Typography>
          <Box sx={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 3,
            p: 2, borderRadius: 2, bgcolor: '#F8FAFC', border: '1px solid #E2E8F0',
          }}>
            <FormControl fullWidth size="small">
              <InputLabel>Source Connection</InputLabel>
              <Select value={form.source_connection} label="Source Connection"
                onChange={(e) => setForm({ ...form, source_connection: e.target.value })}>
                {connections.map(c => <MenuItem key={c.id} value={c.name}>{c.name} ({c.platform})</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Target Connection</InputLabel>
              <Select value={form.target_connection} label="Target Connection"
                onChange={(e) => setForm({ ...form, target_connection: e.target.value })}>
                {connections.map(c => <MenuItem key={c.id} value={c.name}>{c.name} ({c.platform})</MenuItem>)}
              </Select>
            </FormControl>
            <TextField fullWidth label="Source Table" size="small" value={form.source_table}
              onChange={(e) => setForm({ ...form, source_table: e.target.value })}
              placeholder="database.schema.table" />
            <TextField fullWidth label="Target Table" size="small" value={form.target_table}
              onChange={(e) => setForm({ ...form, target_table: e.target.value })}
              placeholder="database.schema.table" />
          </Box>

          {/* Section: Validation Config */}
          <Typography variant="overline" sx={{ color: '#10B981', fontWeight: 700, letterSpacing: 1.2, display: 'block', mb: 1 }}>
            Validation Configuration
          </Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mb: 3 }}>
            <TextField fullWidth label="Join Keys" size="small" value={form.join_keys}
              onChange={(e) => setForm({ ...form, join_keys: e.target.value })}
              placeholder="id, order_id"
              helperText="Comma-separated primary/join keys" />
            <TextField fullWidth label="Check Types" size="small" value={form.check_types}
              onChange={(e) => setForm({ ...form, check_types: e.target.value })}
              placeholder="row_count, data, schema"
              helperText="Comma-separated check types to run" />
            <TextField fullWidth label="WHERE Clause" size="small" value={form.where_clause}
              onChange={(e) => setForm({ ...form, where_clause: e.target.value })}
              placeholder="status = 'ACTIVE'" />
            <TextField fullWidth label="Ignore Columns" size="small" value={form.ignore_columns}
              onChange={(e) => setForm({ ...form, ignore_columns: e.target.value })}
              helperText="Columns to skip during comparison" />
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5, pt: 1 }}>
          <Button onClick={() => setDialogOpen(false)} sx={{ color: '#64748B' }}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} sx={{ px: 4, borderRadius: 2 }}
            disabled={!form.source_connection || !form.source_table || !form.target_connection || !form.target_table}>
            {editEntry ? 'Update' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Import Dialog */}
      <Dialog open={importDialogOpen} onClose={() => setImportDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Import Validation Entries</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ color: '#64748B', mb: 2 }}>
            Upload a CSV or JSON file with columns: group_name, source_connection, source_table,
            target_connection, target_table, join_keys, check_types, strategy, priority, etc.
          </Typography>
          <Button variant="outlined" component="label" startIcon={<UploadFileRoundedIcon />}>
            Choose File
            <input ref={fileInputRef} type="file" hidden accept=".csv,.json" onChange={handleFileImport} />
          </Button>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportDialogOpen(false)}>Cancel</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
