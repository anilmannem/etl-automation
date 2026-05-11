import { useState, useEffect } from 'react';
import {
  Box, FormControl, InputLabel, Select, MenuItem, Typography, Chip,
} from '@mui/material';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import { listConnections } from '../api';

const CSV_OPTION = { id: '__csv__', name: 'CSV', platform: 'csv' };

export default function ConnectionPicker({ label, value, onChange, onConnectionChange, sx }) {
  const [connections, setConnections] = useState([]);

  useEffect(() => {
    listConnections()
      .then((r) => setConnections(r.data))
      .catch(() => setConnections([]));
  }, []);

  const allOptions = [CSV_OPTION, ...connections.filter((c) => c.platform !== 'csv')];
  const selected = allOptions.find((c) => c.id === value);

  return (
    <FormControl fullWidth size="small" sx={sx}>
      <InputLabel>{label}</InputLabel>
      <Select
        value={value || ''}
        onChange={(e) => {
          const id = e.target.value;
          onChange(id);
          if (onConnectionChange) {
            const conn = allOptions.find((c) => c.id === id);
            onConnectionChange(conn || null);
          }
        }}
        label={label}
        renderValue={() =>
          selected ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {selected.id === '__csv__' ? (
                <UploadFileRoundedIcon sx={{ fontSize: 16, color: '#0D9488' }} />
              ) : (
                <StorageRoundedIcon sx={{ fontSize: 16, color: '#3171D6' }} />
              )}
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {selected.name}
              </Typography>
              <Chip
                label={selected.id === '__csv__' ? 'csv' : selected.platform}
                size="small"
                sx={{
                  height: 18, fontSize: '0.6rem', fontWeight: 700,
                  bgcolor: selected.id === '__csv__' ? 'rgba(13,148,136,0.1)' : 'rgba(49,113,214,0.1)',
                  color: selected.id === '__csv__' ? '#0D9488' : '#3171D6',
                }}
              />
            </Box>
          ) : ''
        }
      >
        {allOptions.map((conn) => (
          <MenuItem key={conn.id} value={conn.id}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, width: '100%' }}>
              {conn.id === '__csv__' ? (
                <UploadFileRoundedIcon sx={{ fontSize: 18, color: '#0D9488' }} />
              ) : (
                <StorageRoundedIcon sx={{ fontSize: 18, color: '#3171D6' }} />
              )}
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{conn.name}</Typography>
                <Typography variant="caption" sx={{ color: '#64748B' }}>
                  {conn.id === '__csv__' ? 'Upload a CSV file' : conn.dsn || conn.host || 'Teradata'}
                </Typography>
              </Box>
              <Chip
                label={conn.id === '__csv__' ? 'csv' : conn.platform}
                size="small"
                sx={{
                  height: 18, fontSize: '0.6rem', fontWeight: 700,
                  bgcolor: conn.id === '__csv__' ? 'rgba(13,148,136,0.1)' : 'rgba(49,113,214,0.1)',
                  color: conn.id === '__csv__' ? '#0D9488' : '#3171D6',
                }}
              />
            </Box>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
