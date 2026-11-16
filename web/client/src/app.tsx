import {useEffect} from 'react';
import {Route,Routes,useNavigate} from 'react-router-dom';
import Workbench from './pages/workbench/Workbench';
import Login from './pages/workbench/Login';
import './pages/workbench/workbench.css';
export default function RoutesComponent(){
 const navigate=useNavigate();
 useEffect(()=>{const f=()=>navigate('/login');window.addEventListener('workbench-login-required',f);return()=>window.removeEventListener('workbench-login-required',f)},[navigate]);
 return <Routes><Route index element={<Workbench/>}/><Route path="login" element={<Login/>}/><Route path="*" element={<Login/>}/></Routes>;
}
