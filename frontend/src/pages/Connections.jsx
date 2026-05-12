import { useState, useEffect } from 'react';
import {
  Box, Typography, Button, TextField, Grid, Select, MenuItem,
  FormControl, InputLabel, Alert, IconButton, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, CircularProgress, Tooltip,
} from '@mui/material';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import DeleteRoundedIcon from '@mui/icons-material/DeleteRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CableRoundedIcon from '@mui/icons-material/CableRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import FolderOpenRoundedIcon from '@mui/icons-material/FolderOpenRounded';
import WifiTetheringRoundedIcon from '@mui/icons-material/WifiTetheringRounded';
import { EmptyState } from '../components/Shared';
import {
  listConnections, createConnection, updateConnection,
  deleteConnection, testConnection,
} from '../api';

const EMPTY_CONN = {
  name: '', platform: 'teradata', dsn: '', host: '', port: 0,
  username: '', password: '', database_name: '', schema_name: '',
  file_path: '',
};

const PLATFORM_META = {
  teradata: {
    label: 'Teradata',
    color: '#F97316',
    gradient: 'linear-gradient(135deg, #EA580C, #FB923C)',
    glow: 'rgba(249,115,22,0.25)',
    Icon: StorageRoundedIcon,
  },
  csv: {
    label: 'CSV / Shared Path',
    color: '#0D9488',
    gradient: 'linear-gradient(135deg, #0F766E, #14B8A6)',
    glow: 'rgba(13,148,136,0.25)',
    Icon: FolderOpenRoundedIcon,
  },
};

function ConnectionCard({ conn, onEdit, onDelete, onTest }) {
  const meta = PLATFORM_META[conn.platform] || PLATFORM_META.teradata;
  const Icon = meta.Icon;
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState(null); // null | 'ok' | 'err'

  const handleTest = async (e) => {
    e.stopPropagation();
    setTesting(true);
    setTestStatus(null);
    try {
      const res = await testConnection({
        name: conn.name, platform: conn.platform, dsn: conn.dsn, host: conn.host,
        port: conn.port, username: conn.username, password: '',
        database_name: conn.database_name, schema_name: conn.schema_name,
      });
      setTestStatus(res.data?.success ? 'ok' : 'err');
    } catch {
      setTestStatus('err');
    } finally {
      setTesting(false);
      setTimeout(() => setTestStatus(null), 5000);
    }
  };

  return (
    <Box sx={{
      bgcolor: '#fff',
      borderRadius: '16px',
      border: '1px solid rgba(15,23,42,0.07)',
      boxShadow: '0 1px 3px rgba(15,23,42,0.04), 0 6px 20px rgba(15,23,42,0.05)',
      overflow: 'hidden',
      transition: 'all 0.25s cubic-bezier(0.4,0,0.2,1)',
      '&:hover': {
        transform: 'translateY(-2px)',
        boxShadow: '0 8px 32px rgba(15,23,42,0.10)',
      },
    }}>
      {/* Header gradient strip */}
      <Box sx={{ height: 4, background: meta.gradient }} />

      <Box sx={{ p: 2.5 }}>
        {/* Icon + name row */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
          <Box sx={{
            width: 42, height: 42, borderRadius: '12px',
            background: meta.gradient,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: `0 4px 12px ${meta.glow}`,
            flexShrink: 0,
          }}>
            <Icon sx={{ color: '#fff', fontSize: 20 }} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontSize: '0.9375rem', fontWeight: 700, color: '#0F172A', lineHeight: 1.3 }} noWrap>
              {conn.name}
            </Typography>
            <Typography sx={{ fontSize: '0.7rem', color: '#94A3B8', fontWeight: 500 }}>
              {meta.label}
            </Typography>
          </Box>
          {/* Status dot */}
          {testStatus && (
            <Box sx={{
              width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
              bgcolor: testStatus === 'ok' ? '#059669' : '#DC2626',
              boxShadow: testStatus === 'ok' ? '0 0 0 3px rgba(5,150,105,0.2)' : '0 0 0 3px rgba(220,38,38,0.2)',
            }} />
          )}
        </Box>

        {/* Connection details */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75, mb: 2.5 }}>
          {conn.file_path && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 600, color: '#CBD5E1', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: 44 }}>Path</Typography>
              <Typography sx={{ fontSize: '0.75rem', color: '#475569', fontFamily: 'monospace' }} noWrap>{conn.file_path}</Typography>
            </Box>
          )}
          {conn.host && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 600, color: '#CBD5E1', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: 44 }}>Host</Typography>
              <Typography sx={{ fontSize: '0.75rem', color: '#475569', fontFamily: 'monospace' }} noWrap>{conn.host}</Typography>
            </Box>
          )}
          {conn.database_name && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 600, color: '#CBD5E1', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: 44 }}>DB</Typography>
              <Typography sx={{ fontSize: '0.75rem', color: '#475569', fontFamily: 'monospace' }} noWrap>{conn.database_name}</Typography>
            </Box>
          )}
          {conn.schema_name && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 600, color: '#CBD5E1', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: 44 }}>Schema</Typography>
              <Typography sx={{ fontSize: '0.75rem', color: '#475569', fontFamily: 'monospace' }} noWrap>{conn.schema_name}</Typography>
            </Box>
          )}
        </Box>

        {/* Actions */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', borderTop: '1px solid rgba(15,23,42,0.05)', pt: 2 }}>
          <Button
            size="small" variant="outlined" onClick={handleTest}
            disabled={testing}
            startIcon={testing ? <CircularProgress size={12} color="inherit" /> : <WifiTetheringRoundedIcon sx={{ fontSize: 13 }} />}
            sx={{
              flex: 1, fontSize: '0.72rem', fontWeight: 600, py: 0.625,
              borderColor: testStatus === 'ok' ? 'rgba(5,150,105,0.3)' : testStatus === 'err' ? 'rgba(220,38,38,0.3)' : 'rgba(15,23,42,0.12)',
              color: testStatus === 'ok' ? '#059669' : testStatus === 'err' ? '#DC2626' : '#64748B',
              borderRadius: '8px',
              '&:hover': { borderColor: meta.color, color: meta.color },
            }}
          >
            {testing ? 'Testing…' : testStatus === 'ok' ? 'Connected' : testStatus === 'err' ? 'Failed' : 'Test'}
          </Button>
          <Tooltip title="Edit">
            <IconButton size="small" onClick={() => onEdit(conn)}
              sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: '8px', p: 0.75, color: '#64748B', '&:hover': { color: '#3171D6', borderColor: 'rgba(49,113,214,0.3)', bgcolor: 'rgba(49,113,214,0.04)' } }}>
              <EditRoundedIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete">
            <IconButton size="small" onClick={() => onDelete(conn.id)}
              sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: '8px', p: 0.75, color: '#64748B', '&:hover': { color: '#DC2626', borderColor: 'rgba(220,38,38,0.3)', bgcolor: 'rgba(220,38,38,0.04)' } }}>
              <DeleteRoundedIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
}

function AddCard({ onClick }) {
  return (
    <Box onClick={onClick} sx={{
      borderRadius: '16px',
            border: '2px dashed rgba(49,113,214,0.2)',
      bgcolor: 'rgba(49,113,214,0.02)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: 1.5, p: 4, cursor: 'pointer', minHeight: 200,
      transition: 'all 0.2s',
      '&:hover': {
        border: '2px dashed rgba(49,113,214,0.45)',
        bgcolor: 'rgba(49,113,214,0.05)',
        transform: 'translateY(-2px)',
      },
    }}>
      <Box sx={{
        width: 44, height: 44, borderRadius: '12px',
        background: 'linear-gradient(135deg, rgba(49,113,214,0.12), rgba(49,113,214,0.08))',
        border: '1px solid rgba(49,113,214,0.2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <AddRoundedIcon sx={{ color: '#3171D6', fontSize: 22 }} />
      </Box>
      <Box sx={{ textAlign: 'center' }}>
        <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#3171D6' }}>Add connection</Typography>
        <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8', mt: 0.25 }}>Add your first connection to start validating</Typography>
      </Box>
    </Box>
  );
}

export default function Connections() {
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_CONN });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const fetchConnections = () => {
    setLoading(true);
    listConnections().then((r) => setConnections(r.data || [])).catch(() => setConnections([])).finally(() => setLoading(false));
  };
  useEffect(() => { fetchConnections(); }, []);

  const openCreate = () => { setEditing(null); setForm({ ...EMPTY_CONN }); setTestResult(null); setError(''); setDialogOpen(true); };
  const openEdit = (conn) => {
    setEditing(conn.id);
    setForm({ name: conn.name, platform: conn.platform, dsn: conn.dsn || '', host: conn.host || '', port: conn.port || 0, username: conn.username || '', password: '', database_name: conn.database_name || '', schema_name: conn.schema_name || '', file_path: conn.file_path || '' });
    setTestResult(null); setError(''); setDialogOpen(true);
  };
  const handleDelete = async (id) => { try { await deleteConnection(id); fetchConnections(); } catch (err) { setError(err.response?.data?.detail || 'Delete failed'); } };
  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try { const res = await testConnection(form); setTestResult(res.data); }
    catch (err) { setTestResult({ success: false, message: err.message }); }
    finally { setTesting(false); }
  };
  const handleSave = async () => {
    if (!form.name.trim()) { setError('Connection name is required'); return; }
    setSaving(true); setError('');
    try { editing ? await updateConnection(editing, form) : await createConnection(form); setDialogOpen(false); fetchConnections(); }
    catch (err) { setError(err.response?.data?.detail || 'Save failed'); }
    finally { setSaving(false); }
  };
  const updateField = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <Box sx={{ height: '100%', overflowY: 'auto', p: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 4 }}>
        <Box>
          <Typography sx={{ fontSize: '1.75rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.03em', lineHeight: 1.2 }}>
            Connections
          </Typography>
          <Typography sx={{ fontSize: '0.8125rem', color: '#64748B', mt: 0.5 }}>
            Manage your database connections
          </Typography>
        </Box>
        <Button
          variant="contained" startIcon={<AddRoundedIcon />} onClick={openCreate}
          sx={{
            px: 3, py: 1, fontWeight: 700, fontSize: '0.875rem', borderRadius: '10px',
            background: 'linear-gradient(135deg, #1D55B0, #3171D6)',
            boxShadow: '0 4px 14px rgba(49,113,214,0.3)',
            '&:hover': { transform: 'translateY(-1px)', boxShadow: '0 6px 20px rgba(49,113,214,0.4)' },
          }}
        >
          New Connection
        </Button>
      </Box>

      {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 3, borderRadius: '12px' }}>{error}</Alert>}

      {loading ? (
        <Grid container spacing={2.5}>
          {[1,2,3].map((i) => (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={i}>
              <Box sx={{ bgcolor: '#fff', borderRadius: '16px', p: 2.5, border: '1px solid rgba(15,23,42,0.07)', height: 200 }}>
                <Box sx={{ width: '60%', height: 20, bgcolor: 'rgba(148,163,184,0.1)', borderRadius: 4, mb: 1 }} />
                <Box sx={{ width: '40%', height: 14, bgcolor: 'rgba(148,163,184,0.08)', borderRadius: 4 }} />
              </Box>
            </Grid>
          ))}
        </Grid>
      ) : connections.length === 0 ? (
        <EmptyState
          icon={CableRoundedIcon}
          title="No connections yet"
          subtitle="Add your first connection to start validating data across sources and targets."
          action={
            <Button variant="contained" startIcon={<AddRoundedIcon />} onClick={openCreate}
              sx={{ px: 3, fontWeight: 700, background: 'linear-gradient(135deg, #1D55B0, #3171D6)', boxShadow: '0 4px 14px rgba(49,113,214,0.3)' }}>
              Add your first connection
            </Button>
          }
        />
      ) : (
        <Grid container spacing={2.5}>
          {connections.map((conn) => (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={conn.id}>
              <ConnectionCard conn={conn} onEdit={openEdit} onDelete={handleDelete} />
            </Grid>
          ))}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <AddCard onClick={openCreate} />
          </Grid>
        </Grid>
      )}

      {/* Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth
        PaperProps={{ sx: { borderRadius: '20px', border: '1px solid rgba(15,23,42,0.08)', boxShadow: '0 24px 80px rgba(15,23,42,0.15)' } }}>
        <DialogTitle sx={{ pb: 1 }}>
          <Typography sx={{ fontSize: '1.125rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.02em' }}>
            {editing ? 'Edit Connection' : 'New Connection'}
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8', mt: 0.25 }}>
            Configure how to connect to your data source
          </Typography>
        </DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          {error && <Alert severity="error" sx={{ mb: 2, borderRadius: '10px' }} onClose={() => setError('')}>{error}</Alert>}
          {testResult && (
            <Alert severity={testResult.success ? 'success' : 'error'} sx={{ mb: 2, borderRadius: '10px' }}>
              {testResult.message}
            </Alert>
          )}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField fullWidth size="small" label="Connection Name" value={form.name} onChange={(e) => updateField('name', e.target.value)} placeholder="e.g. prod-teradata" />
            <FormControl fullWidth size="small">
              <InputLabel>Platform</InputLabel>
              <Select value={form.platform} onChange={(e) => updateField('platform', e.target.value)} label="Platform">
                <MenuItem value="teradata">Teradata</MenuItem>
                <MenuItem value="csv">CSV / Shared Path</MenuItem>
              </Select>
            </FormControl>
            {form.platform === 'csv' ? (
              <TextField
                fullWidth size="small"
                label="Shared / Network Path"
                value={form.file_path}
                onChange={(e) => updateField('file_path', e.target.value)}
                placeholder="/mnt/shared/data/ or \\\\server\\share\\folder"
                helperText="Directory path on a shared/network drive accessible to the server"
              />
            ) : (
              <>
                <TextField fullWidth size="small" label="DSN (optional)" value={form.dsn} onChange={(e) => updateField('dsn', e.target.value)} />
                <Grid container spacing={2}>
                  <Grid size={{ xs: 8 }}>
                    <TextField fullWidth size="small" label="Host" value={form.host} onChange={(e) => updateField('host', e.target.value)} />
                  </Grid>
                  <Grid size={{ xs: 4 }}>
                    <TextField fullWidth size="small" label="Port" type="number" value={form.port} onChange={(e) => updateField('port', parseInt(e.target.value) || 0)} />
                  </Grid>
                </Grid>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 6 }}>
                    <TextField fullWidth size="small" label="Username" value={form.username} onChange={(e) => updateField('username', e.target.value)} />
                  </Grid>
                  <Grid size={{ xs: 6 }}>
                    <TextField fullWidth size="small" label="Password" type="password" value={form.password} onChange={(e) => updateField('password', e.target.value)} />
                  </Grid>
                </Grid>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 6 }}>
                    <TextField fullWidth size="small" label="Database" value={form.database_name} onChange={(e) => updateField('database_name', e.target.value)} />
                  </Grid>
                  <Grid size={{ xs: 6 }}>
                    <TextField fullWidth size="small" label="Schema" value={form.schema_name} onChange={(e) => updateField('schema_name', e.target.value)} />
                  </Grid>
                </Grid>
              </>
            )}

          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3, gap: 1 }}>
          <Button onClick={handleTest} disabled={testing} variant="outlined"
            startIcon={testing ? <CircularProgress size={14} color="inherit" /> : <WifiTetheringRoundedIcon />}
            sx={{ fontWeight: 600, borderRadius: '10px', borderColor: 'rgba(15,23,42,0.15)', color: '#475569' }}>
            {testing ? 'Testing…' : 'Test'}
          </Button>
          <Box sx={{ flex: 1 }} />
          <Button onClick={() => setDialogOpen(false)} sx={{ color: '#64748B', fontWeight: 600 }}>Cancel</Button>
          <Button onClick={handleSave} variant="contained" disabled={saving}
            startIcon={saving ? <CircularProgress size={14} color="inherit" /> : null}
            sx={{ fontWeight: 700, borderRadius: '10px', background: 'linear-gradient(135deg, #1D55B0, #3171D6)', px: 3 }}>
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
