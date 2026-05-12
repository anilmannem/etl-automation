import { useLocation, useNavigate } from 'react-router-dom';
import { Box, Drawer, Tooltip } from '@mui/material';
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded';
import PlayCircleFilledRoundedIcon from '@mui/icons-material/PlayCircleFilledRounded';
import BoltRoundedIcon from '@mui/icons-material/BoltRounded';
import CableRoundedIcon from '@mui/icons-material/CableRounded';

const WIDTH = 64;

const NAV = [
  { label: 'Dashboard', icon: DashboardRoundedIcon, path: '/' },
  { label: 'Ad-hoc Test', icon: BoltRoundedIcon, path: '/adhoc' },
  { label: 'Test Suite', icon: PlayCircleFilledRoundedIcon, path: '/suite' },
  { label: 'Connections', icon: CableRoundedIcon, path: '/connections' },
];

const NAVY_HOVER = '#525B7E';
const NAVY_ACTIVE = '#EB5149';

/* App logo — uses the real SVG file, inverted to white for dark sidebar */
function AppLogo({ size = 28 }) {
  return (
    <img
      src="/favicon.svg"
      width={size}
      height={size}
      alt="logo"
      style={{ filter: 'brightness(0) invert(1)', display: 'block' }}
    />
  );
}

export default function Sidebar() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: WIDTH,
          bgcolor: '#071446',
          boxSizing: 'border-box',
          border: 'none',
          overflow: 'hidden',
        },
      }}
    >
      {/* Single inner column — owns all layout, top-aligned */}
      <Box sx={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        width: '100%', pt: 1.5, pb: 1.5,
      }}>
      {/* App logo — top, clickable to home */}
      <Tooltip title="ETL Automation" placement="right" arrow>
        <Box
          onClick={() => navigate('/')}
          sx={{
            width: 40, height: 40, borderRadius: 2.5,
            bgcolor: 'rgba(255,255,255,0.08)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', mb: 1.5, flexShrink: 0,
            transition: 'opacity 0.15s',
            '&:hover': { opacity: 0.85 },
          }}
        >
          <AppLogo size={28} />
        </Box>
      </Tooltip>

      {/* Separator */}
      <Box sx={{ width: 32, height: 1, bgcolor: 'rgba(255,255,255,0.07)', mb: 1 }} />

      {/* Nav items — packed immediately below separator */}
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.25, width: '100%', px: 0.75 }}>
        {NAV.map((item) => {
          const active = pathname === item.path;
          const Icon = item.icon;
          return (
            <Tooltip key={item.path} title={item.label} placement="right" arrow>
              <Box
                onClick={() => navigate(item.path)}
                sx={{
                  width: '100%', height: 44,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  borderRadius: '10px', cursor: 'pointer',
                  bgcolor: active ? NAVY_ACTIVE : 'transparent',
                  position: 'relative',
                  transition: 'background 0.15s ease',
                  '&:hover': { bgcolor: active ? NAVY_ACTIVE : NAVY_HOVER },
                  '&:hover .nav-icon': { opacity: 1 },
                }}
              >
                <Icon
                  className="nav-icon"
                  sx={{
                    fontSize: 20,
                    color: '#fff',
                    opacity: active ? 1 : 0.55,
                    transition: 'opacity 0.15s ease',
                  }}
                />
              </Box>
            </Tooltip>
          );
        })}
      </Box>
      </Box>
    </Drawer>
  );
}
