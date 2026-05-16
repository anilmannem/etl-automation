import { useState, useEffect, useRef } from 'react';
import {
  Box, Typography, Button, TextField, Grid, Select, MenuItem,
  FormControl, InputLabel, Alert, IconButton, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, CircularProgress, Tooltip, Switch,
  FormControlLabel, Tab, Tabs, LinearProgress, Paper,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import DeleteRoundedIcon from '@mui/icons-material/DeleteRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import FilterListRoundedIcon from '@mui/icons-material/FilterListRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import { EmptyState } from '../components/Shared';
import {
  listMetadata, createMetadata, updateMetadata, deleteMetadata,
  bulkImportMetadata, runFromMetadata, listConnections,
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
const SCHEDULES = ['hourly', 'daily', 'weekly', 'monthly', 'on-demand'];
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
      <Chip label={entry.schedule} size="small" variant="outlined" sx={{ fontSize: 11, height: 22, color: '#8B5CF6' }} />
      {entry.tags && (
        <Chip label={entry.tags.split(',')[0]} size="small" sx={{ fontSize: 10, height: 20, bgcolor: '#EDE9FE' }} />
      )}
      <Tooltip title="Run Validation"><IconButton size="small" onClick={() => onRun(entry)}><PlayArrowRoundedIcon fontSize="small" sx={{ color: '#10B981' }} /></IconButton></Tooltip>
      <Tooltip title="Edit"><IconButton size="small" onClick={() => onEdit(entry)}><EditRoundedIcon fontSize="small" /></IconButton></Tooltip>
      <Tooltip title="Delete"><IconButton size="small" onClick={() => onDelete(entry)}><DeleteRoundedIcon fontSize="small" sx={{ color: '#DC2626' }} /></IconButton></Tooltip>
    </Box>
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
    try {
      const res = await runFromMetadata({ ids: [entry.id] });
      setRunResult(res.data);
      setSuccess(`Validation complete: ${res.data.passed} passed, ${res.data.failed} failed`);
    } catch (e) {
      setError(e.response?.data?.detail || 'Run failed');
    } finally {
      setRunning(false);
    }
  };

  const handleRunGroup = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const res = await runFromMetadata({ group_name: filterGroup || '' });
      setRunResult(res.data);
      setSuccess(`Batch complete: ${res.data.passed}/${res.data.total} passed`);
    } catch (e) {
      setError(e.response?.data?.detail || 'Batch run failed');
    } finally {
      setRunning(false);
    }
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
            Manage all table validations from one place — no YAML needed
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" startIcon={<UploadFileRoundedIcon />} onClick={() => setImportDialogOpen(true)}>
            Import
          </Button>
          <Button variant="outlined" color="success" startIcon={<PlayArrowRoundedIcon />}
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

      {/* Run Results Banner */}
      {runResult && (
        <Alert severity={runResult.failed > 0 ? 'warning' : 'success'} sx={{ mb: 2 }} onClose={() => setRunResult(null)}>
          Batch {runResult.batch_id}: {runResult.passed} passed, {runResult.failed} failed, {runResult.errors} errors
        </Alert>
      )}

      {running && <LinearProgress sx={{ mb: 2 }} />}

      {/* Table List */}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress /></Box>
      ) : entries.length === 0 ? (
        <EmptyState
          icon={<StorageRoundedIcon sx={{ fontSize: 48, color: '#CBD5E1' }} />}
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
            <Typography variant="caption" sx={{ width: 80, fontWeight: 600, color: '#475569' }}>Schedule</Typography>
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
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editEntry ? 'Edit Validation Entry' : 'Add Validation Entry'}</DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={6}>
              <TextField fullWidth label="Group Name" size="small" value={form.group_name}
                onChange={(e) => setForm({ ...form, group_name: e.target.value })} />
            </Grid>
            <Grid item xs={3}>
              <FormControl fullWidth size="small">
                <InputLabel>Strategy</InputLabel>
                <Select value={form.strategy} label="Strategy" onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
                  {STRATEGIES.map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={3}>
              <FormControl fullWidth size="small">
                <InputLabel>Schedule</InputLabel>
                <Select value={form.schedule} label="Schedule" onChange={(e) => setForm({ ...form, schedule: e.target.value })}>
                  {SCHEDULES.map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>

            {/* Source */}
            <Grid item xs={6}>
              <FormControl fullWidth size="small">
                <InputLabel>Source Connection</InputLabel>
                <Select value={form.source_connection} label="Source Connection"
                  onChange={(e) => setForm({ ...form, source_connection: e.target.value })}>
                  {connections.map(c => <MenuItem key={c.id} value={c.name}>{c.name} ({c.platform})</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Source Table" size="small" value={form.source_table}
                onChange={(e) => setForm({ ...form, source_table: e.target.value })}
                placeholder="schema.table_name" />
            </Grid>

            {/* Target */}
            <Grid item xs={6}>
              <FormControl fullWidth size="small">
                <InputLabel>Target Connection</InputLabel>
                <Select value={form.target_connection} label="Target Connection"
                  onChange={(e) => setForm({ ...form, target_connection: e.target.value })}>
                  {connections.map(c => <MenuItem key={c.id} value={c.name}>{c.name} ({c.platform})</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Target Table" size="small" value={form.target_table}
                onChange={(e) => setForm({ ...form, target_table: e.target.value })}
                placeholder="schema.table_name" />
            </Grid>

            {/* Keys & Checks */}
            <Grid item xs={6}>
              <TextField fullWidth label="Join Keys (comma-separated)" size="small" value={form.join_keys}
                onChange={(e) => setForm({ ...form, join_keys: e.target.value })}
                placeholder="id, order_id" />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Check Types (comma-separated)" size="small" value={form.check_types}
                onChange={(e) => setForm({ ...form, check_types: e.target.value })}
                placeholder="row_count,data,schema" />
            </Grid>

            {/* Options */}
            <Grid item xs={3}>
              <TextField fullWidth label="Priority" size="small" type="number" value={form.priority}
                onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} />
            </Grid>
            <Grid item xs={3}>
              <TextField fullWidth label="Tolerance" size="small" type="number" value={form.tolerance}
                onChange={(e) => setForm({ ...form, tolerance: Number(e.target.value) })} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Ignore Columns" size="small" value={form.ignore_columns}
                onChange={(e) => setForm({ ...form, ignore_columns: e.target.value })} />
            </Grid>

            {/* Where / Timestamp */}
            <Grid item xs={6}>
              <TextField fullWidth label="WHERE Clause" size="small" value={form.where_clause}
                onChange={(e) => setForm({ ...form, where_clause: e.target.value })}
                placeholder="status = 'ACTIVE'" />
            </Grid>
            <Grid item xs={3}>
              <TextField fullWidth label="Timestamp Column" size="small" value={form.timestamp_column}
                onChange={(e) => setForm({ ...form, timestamp_column: e.target.value })} />
            </Grid>
            <Grid item xs={3}>
              <FormControlLabel
                control={<Switch checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />}
                label="Active"
              />
            </Grid>

            {/* Tags & Notes */}
            <Grid item xs={6}>
              <TextField fullWidth label="Tags (comma-separated)" size="small" value={form.tags}
                onChange={(e) => setForm({ ...form, tags: e.target.value })}
                placeholder="finance, critical" />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Notes" size="small" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave}
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
