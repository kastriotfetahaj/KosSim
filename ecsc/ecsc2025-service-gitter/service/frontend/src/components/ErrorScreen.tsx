import React from "react";

interface ErrorScreenProps {
  title: string;
  message: string;
}

const ErrorScreen: React.FC<ErrorScreenProps> = ({ title, message }) => {
  return (
    <div className="flex flex-col items-center justify-center h-full text-white w-full">
      <div className="text-center font-saiba">
        <h1 className="text-7xl font-bold text-red-500 mb-4 animate-glitch" style={{ textShadow: '0 0 5px #ff000099, 0 0 10px #ff000099, 0 0 15px #ff000099' }}>{title}</h1>
        <p className="text-2xl text-gray-300 animate-glitch-delay" style={{ textShadow: '0 0 3px #cccccc99, 0 0 5px #cccccc99' }}>{message}</p>
      </div>
    </div>
  );
};

export default ErrorScreen; 