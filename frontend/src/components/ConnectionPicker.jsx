import { useState, useEffect } from 'react';
import {
  Box, FormControl, InputLabel, Select, MenuItem, Typography, Chip,
} from '@mui/material';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import FolderOpenRoundedIcon from '@mui/icons-material/FolderOpenRounded';
import { listConnections } from '../api';

const CSV_OPTION = { id: '__csv__', name: 'CSV (Upload / Path)', platform: 'csv' };

export default function ConnectionPicker({ label, value, onChange, onConnectionChange, sx }) {
  const [connections, setConnections] = useState([]);

  useEffect(() => {
    listConnections()
      .then((r) => setConnections(r.data))
      .catch(() => setConnections([]));
  }, []);

  const allOptions = [CSV_OPTION, ...connections];
  const selected = allOptions.find((c) => c.id === value);

  const isCsvLike = (conn) => conn.id === '__csv__' || conn.platform === 'csv';
  const getIcon = (conn) => {
    if (conn.id === '__csv__') return <UploadFileRoundedIcon sx={{ fontSize: 16, color: '#0D9488' }} />;
    if (conn.platform === 'csv') return <FolderOpenRoundedIcon sx={{ fontSize: 16, color: '#0D9488' }} />;
    return <StorageRoundedIcon sx={{ fontSize: 16, color: '#3171D6' }} />;
  };
  const getIconLg = (conn) => {
    if (conn.id === '__csv__') return <UploadFileRoundedIcon sx={{ fontSize: 18, color: '#0D9488' }} />;
    if (conn.platform === 'csv') return <FolderOpenRoundedIcon sx={{ fontSize: 18, color: '#0D9488' }} />;
    return <StorageRoundedIcon sx={{ fontSize: 18, color: '#3171D6' }} />;
  };

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
              {getIcon(selected)}
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {selected.name}
              </Typography>
              <Chip
                label={selected.platform === 'csv' ? 'csv' : selected.platform}
                size="small"
                sx={{
                  height: 18, fontSize: '0.6rem', fontWeight: 700,
                  bgcolor: isCsvLike(selected) ? 'rgba(13,148,136,0.1)' : 'rgba(49,113,214,0.1)',
                  color: isCsvLike(selected) ? '#0D9488' : '#3171D6',
                }}
              />
            </Box>
          ) : ''
        }
      >
        {allOptions.map((conn) => (
          <MenuItem key={conn.id} value={conn.id}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, width: '100%' }}>
              {getIconLg(conn)}
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{conn.name}</Typography>
                <Typography variant="caption" sx={{ color: '#64748B' }}>
                  {conn.id === '__csv__' ? 'Enter file path manually' : conn.platform === 'csv' ? (conn.file_path || 'Shared path') : conn.dsn || conn.host || 'Teradata'}
                </Typography>
              </Box>
              <Chip
                label={conn.platform === 'csv' ? 'csv' : conn.platform}
                size="small"
                sx={{
                  height: 18, fontSize: '0.6rem', fontWeight: 700,
                  bgcolor: isCsvLike(conn) ? 'rgba(13,148,136,0.1)' : 'rgba(49,113,214,0.1)',
                  color: isCsvLike(conn) ? '#0D9488' : '#3171D6',
                }}
              />
            </Box>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
