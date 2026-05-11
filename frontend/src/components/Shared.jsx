import { Box, Typography } from '@mui/material';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import ErrorOutlineRoundedIcon from '@mui/icons-material/ErrorOutlineRounded';
import RemoveCircleOutlineRoundedIcon from '@mui/icons-material/RemoveCircleOutlineRounded';

const STATUS_CONFIG = {
  Pass: { color: '#059669', bg: '#ECFDF5', border: '#A7F3D0', icon: CheckCircleRoundedIcon, label: 'Pass' },
  Fail: { color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', icon: CancelRoundedIcon, label: 'Fail' },
  Warning: { color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', icon: WarningAmberRoundedIcon, label: 'Warning' },
  Error: { color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', icon: ErrorOutlineRoundedIcon, label: 'Error' },
  'Not Applicable': { color: '#6B7280', bg: '#F9FAFB', border: '#E5E7EB', icon: RemoveCircleOutlineRoundedIcon, label: 'N/A' },
};

export function StatusChip({ status, size = 'small' }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG['Not Applicable'];
  const Icon = cfg.icon;
  return (
    <Box sx={{
      display: 'inline-flex', alignItems: 'center', gap: 0.5,
      px: 1.25, py: 0.375,
      borderRadius: '20px',
      bgcolor: cfg.bg,
      border: `1px solid ${cfg.border}`,
    }}>
      <Icon sx={{ fontSize: 12, color: cfg.color }} />
      <Typography sx={{ fontSize: '0.7rem', fontWeight: 700, color: cfg.color, lineHeight: 1 }}>{cfg.label}</Typography>
    </Box>
  );
}

export function EmptyState({ icon: Icon, title, subtitle, action }) {
  return (
    <Box sx={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      py: 10, px: 4, textAlign: 'center',
    }}>
      <Box sx={{
        width: 72, height: 72, borderRadius: '20px',
        background: 'linear-gradient(135deg, rgba(49,113,214,0.08) 0%, rgba(49,113,214,0.04) 100%)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        mb: 3,
        border: '1px solid rgba(49,113,214,0.1)',
      }}>
        {Icon && <Icon sx={{ fontSize: 32, color: '#93C5FD' }} />}
      </Box>
      <Typography sx={{ fontSize: '1.125rem', fontWeight: 700, color: '#0F172A', mb: 0.75 }}>
        {title}
      </Typography>
      <Typography sx={{ fontSize: '0.875rem', color: '#64748B', maxWidth: 400, lineHeight: 1.6, mb: action ? 3 : 0 }}>
        {subtitle}
      </Typography>
      {action}
    </Box>
  );
}
